#include "packet_capture.hpp"

#include <algorithm>
#include <cstring>
#include <limits>

#if defined(__APPLE__)
#include <mach/mach.h>
#include <mach/mach_vm.h>
#elif defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace fa {
namespace {

bool Overlap(const void *first, uint64_t first_size, const void *second,
             uint64_t second_size) noexcept {
  if (first_size == 0 || second_size == 0) return false;
  const auto a = reinterpret_cast<uintptr_t>(first);
  const auto b = reinterpret_cast<uintptr_t>(second);
  if (first_size > UINTPTR_MAX - a || second_size > UINTPTR_MAX - b) return true;
  return a < b + second_size && b < a + first_size;
}

bool RangeOverflows(const void *source, uint64_t bytes) noexcept {
  return bytes > UINTPTR_MAX - reinterpret_cast<uintptr_t>(source);
}

/* One bounded, kernel-checked read from this process into owned storage.
 * No remote task/handle is opened and a failed/short copy is never published.
 * A successful candidate uses at most two such calls, with no retry in-frame.
 */
bool CopyReadableMemory(void *destination, const void *source,
                         uint64_t bytes) noexcept {
#if defined(__APPLE__)
  mach_vm_size_t copied = 0;
  const auto result = mach_vm_read_overwrite(
      mach_task_self(), reinterpret_cast<mach_vm_address_t>(source),
      static_cast<mach_vm_size_t>(bytes),
      reinterpret_cast<mach_vm_address_t>(destination), &copied);
  return result == KERN_SUCCESS && copied == bytes;
#elif defined(_WIN32)
  SIZE_T copied = 0;
  return ReadProcessMemory(GetCurrentProcess(), source, destination,
                            static_cast<SIZE_T>(bytes), &copied) != 0 &&
         copied == bytes;
#else
  (void)destination;
  (void)source;
  (void)bytes;
  return false;
#endif
}

bool ValidRequest(const fa_packet_request_v1 &request) noexcept {
  return request.struct_size == sizeof(request) && request.flags == 0 &&
         request.reserved0 == 0 && request.reserved1 == 0 &&
         request.min_keys >= 1 && request.max_keys >= request.min_keys &&
         request.max_keys <= FA_PACKET_MAX_KEYS &&
         request.min_payload_bytes >= 4 &&
         request.max_payload_bytes >= request.min_payload_bytes &&
         request.max_payload_bytes <= FA_PACKET_MAX_PAYLOAD_BYTES &&
         request.max_total_bytes <= FA_PACKET_MAX_TOTAL_BYTES &&
         static_cast<uint64_t>(request.min_keys) * 8 +
                 request.min_payload_bytes <= request.max_total_bytes;
}

}  // namespace

int PacketCapture::DefaultRequest(fa_packet_request_v1 *request,
                                   uint32_t request_size) noexcept {
  if (request == nullptr) return FA_PACKET_INVALID_ARGUMENT;
  if (request_size < sizeof(*request)) return FA_PACKET_BUFFER_TOO_SMALL;
  if (request_size != sizeof(*request)) return FA_PACKET_INVALID_ARGUMENT;
  *request = {};
  request->version = FA_PACKET_ABI_VERSION;
  request->struct_size = sizeof(*request);
  request->min_keys = 1;
  request->max_keys = FA_PACKET_MAX_KEYS;
  request->min_payload_bytes = 4;
  request->max_payload_bytes = FA_PACKET_MAX_PAYLOAD_BYTES;
  request->max_total_bytes = FA_PACKET_MAX_TOTAL_BYTES;
  return FA_PACKET_OK;
}

int PacketCapture::SetLegacyCaptureEnabled(std::atomic<uint32_t> &enabled,
                                           bool value) noexcept {
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    enabled.store(value ? 1 : 0, std::memory_order_release);
    if (!value) RequestCancellation();
    return FA_OBSERVER_OK;
  } catch (...) {
    if (!value) {
      enabled.store(0, std::memory_order_release);
      RequestCancellation();
    }
    return FA_OBSERVER_CONTROL_EXCEPTION;
  }
}

int PacketCapture::Arm(const fa_packet_request_v1 *request, uint32_t request_size,
                       const std::atomic<uint32_t> &legacy_enabled,
                       uint64_t *out_capture_id) noexcept {
  if (out_capture_id == nullptr) return FA_PACKET_INVALID_ARGUMENT;
  *out_capture_id = 0;
  if (request == nullptr) return FA_PACKET_INVALID_ARGUMENT;
  if (request_size < sizeof(*request)) return FA_PACKET_BUFFER_TOO_SMALL;
  if (request_size != sizeof(*request)) return FA_PACKET_INVALID_ARGUMENT;
  const auto desired = *request;
  if (desired.version != FA_PACKET_ABI_VERSION) {
    return FA_PACKET_UNSUPPORTED_VERSION;
  }
  if (!ValidRequest(desired)) return FA_PACKET_INVALID_ARGUMENT;
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    if (legacy_enabled.load(std::memory_order_acquire) == 0) {
      return FA_PACKET_LEGACY_CAPTURE_DISABLED;
    }
    const auto state = state_.load(std::memory_order_acquire);
    if (state == FA_PACKET_READY || state == FA_PACKET_CANCELLED) {
      return FA_PACKET_NEEDS_RELEASE;
    }
    if (state != FA_PACKET_IDLE) return FA_PACKET_BUSY;
    if (last_assigned_id_ == UINT64_MAX) return FA_PACKET_ID_EXHAUSTED;
    request_ = desired;
    active_id_ = ++last_assigned_id_;
    captured_ = {};
    checked_packets_.store(0, std::memory_order_relaxed);
    skipped_packets_.store(0, std::memory_order_relaxed);
    last_skip_reason_.store(FA_PACKET_SKIP_NONE, std::memory_order_relaxed);
    *out_capture_id = active_id_;
    state_.store(FA_PACKET_ARMED, std::memory_order_release);
    return FA_PACKET_OK;
  } catch (...) {
    return FA_PACKET_CONTROL_EXCEPTION;
  }
}

void PacketCapture::FinishCancelled() noexcept {
  last_skip_reason_.store(FA_PACKET_SKIP_CANCELLED, std::memory_order_relaxed);
  state_.store(FA_PACKET_CANCELLED, std::memory_order_release);
}

void PacketCapture::FinishSkipped(uint32_t reason) noexcept {
  last_skip_reason_.store(reason, std::memory_order_relaxed);
  skipped_packets_.fetch_add(1, std::memory_order_relaxed);
  uint32_t expected = FA_PACKET_WRITING;
  if (!state_.compare_exchange_strong(expected, FA_PACKET_ARMED,
                                       std::memory_order_release,
                                       std::memory_order_acquire)) {
    FinishCancelled();
  }
}

void PacketCapture::TryCapture(uint64_t call_sequence, const void *keys_header,
                                const void *payload_header) noexcept {
  auto state = state_.load(std::memory_order_acquire);
  if (state != FA_PACKET_ARMED) {
    if (state == FA_PACKET_WRITING || state == FA_PACKET_CANCELLING) {
      busy_skipped_total_.fetch_add(1, std::memory_order_relaxed);
    }
    return;
  }
  if (!state_.compare_exchange_strong(state, FA_PACKET_WRITING,
                                      std::memory_order_acq_rel,
                                      std::memory_order_acquire)) {
    busy_skipped_total_.fetch_add(1, std::memory_order_relaxed);
    return;
  }

  /* No control operation can change request_/active_id_ or reuse buffers while
   * WRITING/CANCELLING. All plain reads happen after winning this acquire CAS.
   */
  checked_packets_.fetch_add(1, std::memory_order_relaxed);
  if (keys_header == nullptr || payload_header == nullptr) {
    FinishSkipped(FA_PACKET_SKIP_NULL_HEADER);
    return;
  }
  uint64_t key_count = 0;
  uint64_t payload_count = 0;
  std::memcpy(&key_count, static_cast<const unsigned char *>(keys_header) + 8, 8);
  std::memcpy(&payload_count,
               static_cast<const unsigned char *>(payload_header) + 8, 8);
  if (key_count > UINT64_MAX / 8) {
    FinishSkipped(FA_PACKET_SKIP_KEYS_SIZE_OVERFLOW);
    return;
  }
  if (key_count < request_.min_keys) {
    FinishSkipped(FA_PACKET_SKIP_KEYS_BELOW_MINIMUM);
    return;
  }
  if (key_count > request_.max_keys) {
    FinishSkipped(FA_PACKET_SKIP_KEYS_OVER_CAP);
    return;
  }
  if (payload_count < request_.min_payload_bytes) {
    FinishSkipped(FA_PACKET_SKIP_PAYLOAD_BELOW_MINIMUM);
    return;
  }
  if (payload_count > request_.max_payload_bytes) {
    FinishSkipped(FA_PACKET_SKIP_PAYLOAD_OVER_CAP);
    return;
  }
  const auto key_bytes = key_count * 8;
  if (payload_count > UINT64_MAX - key_bytes ||
      key_bytes + payload_count > request_.max_total_bytes) {
    FinishSkipped(FA_PACKET_SKIP_TOTAL_OVER_CAP);
    return;
  }
  const void *key_data = nullptr;
  const void *payload_data = nullptr;
  std::memcpy(&key_data, keys_header, sizeof(key_data));
  std::memcpy(&payload_data, payload_header, sizeof(payload_data));
  if (key_count != 0 && key_data == nullptr) {
    FinishSkipped(FA_PACKET_SKIP_NULL_KEYS_DATA);
    return;
  }
  if (payload_count != 0 && payload_data == nullptr) {
    FinishSkipped(FA_PACKET_SKIP_NULL_PAYLOAD_DATA);
    return;
  }
  if (RangeOverflows(key_data, key_bytes) ||
      RangeOverflows(payload_data, payload_count)) {
    FinishSkipped(FA_PACKET_SKIP_SOURCE_RANGE_OVERFLOW);
    return;
  }
  if (state_.load(std::memory_order_acquire) != FA_PACKET_WRITING) {
    FinishCancelled();
    return;
  }

  fa_packet_manifest_v1 completed{};
  completed.version = FA_PACKET_ABI_VERSION;
  completed.struct_size = sizeof(completed);
  completed.state = FA_PACKET_READY;
  completed.flags = FA_PACKET_COUNTS_KNOWN | FA_PACKET_COMPLETE |
                    FA_PACKET_ORIGINAL_RESULT_UNKNOWN;
  completed.capture_id = active_id_;
  completed.call_sequence = call_sequence;
  completed.monotonic_ns = MonotonicNanosecondsForControl();
  completed.native_thread_id = NativeThreadIdForCapture();
  completed.original_keys_count = key_count;
  completed.original_payload_count = payload_count;
  completed.copied_keys_bytes = key_bytes;
  completed.copied_payload_bytes = payload_count;
  if (!CopyReadableMemory(keys_.data(), key_data, key_bytes)) {
    FinishSkipped(FA_PACKET_SKIP_UNREADABLE_KEYS);
    return;
  }
  if (!CopyReadableMemory(payload_.data(), payload_data, payload_count)) {
    FinishSkipped(FA_PACKET_SKIP_UNREADABLE_PAYLOAD);
    return;
  }
  captured_ = completed;
  last_skip_reason_.store(FA_PACKET_SKIP_NONE, std::memory_order_relaxed);
  uint32_t expected = FA_PACKET_WRITING;
  if (!state_.compare_exchange_strong(expected, FA_PACKET_READY,
                                      std::memory_order_release,
                                      std::memory_order_acquire)) {
    FinishCancelled();
  }
}

int PacketCapture::CheckOutput(uint32_t version,
                               fa_packet_manifest_v1 *manifest,
                               uint32_t manifest_size) noexcept {
  if (version != FA_PACKET_ABI_VERSION) return FA_PACKET_UNSUPPORTED_VERSION;
  if (manifest == nullptr) return FA_PACKET_INVALID_ARGUMENT;
  if (manifest_size < sizeof(*manifest)) return FA_PACKET_BUFFER_TOO_SMALL;
  *manifest = {};
  manifest->version = FA_PACKET_ABI_VERSION;
  manifest->struct_size = sizeof(*manifest);
  return FA_PACKET_OK;
}

int PacketCapture::CheckCaptureIdLocked(uint64_t capture_id) const noexcept {
  if (capture_id == 0) return FA_PACKET_INVALID_ARGUMENT;
  if (active_id_ == 0) return FA_PACKET_NO_CAPTURE;
  return capture_id == active_id_ ? FA_PACKET_OK : FA_PACKET_WRONG_CAPTURE_ID;
}

void PacketCapture::FillManifestLocked(
    const std::atomic<uint32_t> &legacy_enabled,
    fa_packet_manifest_v1 &manifest) const noexcept {
  const auto state = state_.load(std::memory_order_acquire);
  if (state == FA_PACKET_READY) {
    manifest = captured_;
  } else {
    manifest = {};
    manifest.version = FA_PACKET_ABI_VERSION;
    manifest.struct_size = sizeof(manifest);
    manifest.capture_id = active_id_;
  }
  manifest.state = state;
  if (state == FA_PACKET_CANCELLING || state == FA_PACKET_CANCELLED) {
    manifest.flags |= FA_PACKET_CANCEL_REQUESTED;
  }
  if (legacy_enabled.load(std::memory_order_acquire) == 0) {
    manifest.flags |= FA_PACKET_LEGACY_DISABLED;
  }
  manifest.checked_packets = checked_packets_.load(std::memory_order_relaxed);
  manifest.skipped_packets = skipped_packets_.load(std::memory_order_relaxed);
  manifest.last_skip_reason = last_skip_reason_.load(std::memory_order_relaxed);
  manifest.busy_skipped_total =
      busy_skipped_total_.load(std::memory_order_relaxed);
}

int PacketCapture::GetManifest(uint32_t version, uint64_t capture_id,
                                const std::atomic<uint32_t> &legacy_enabled,
                                fa_packet_manifest_v1 *manifest,
                                uint32_t manifest_size) noexcept {
  const auto validation = CheckOutput(version, manifest, manifest_size);
  if (validation != FA_PACKET_OK) return validation;
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    if (capture_id != 0) {
      const auto result = CheckCaptureIdLocked(capture_id);
      if (result != FA_PACKET_OK) return result;
    }
    FillManifestLocked(legacy_enabled, *manifest);
    return FA_PACKET_OK;
  } catch (...) {
    return FA_PACKET_CONTROL_EXCEPTION;
  }
}

int PacketCapture::Copy(uint32_t version, uint64_t capture_id, void *keys_buffer,
                        uint64_t keys_capacity, void *payload_buffer,
                        uint64_t payload_capacity,
                        const std::atomic<uint32_t> &legacy_enabled,
                        fa_packet_manifest_v1 *manifest,
                        uint32_t manifest_size) noexcept {
  const auto validation = CheckOutput(version, manifest, manifest_size);
  if (validation != FA_PACKET_OK) return validation;
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    const auto id_result = CheckCaptureIdLocked(capture_id);
    if (id_result != FA_PACKET_OK) return id_result;
    FillManifestLocked(legacy_enabled, *manifest);
    if (manifest->state == FA_PACKET_CANCELLED) return FA_PACKET_CANCELLED_RESULT;
    if (manifest->state != FA_PACKET_READY) return FA_PACKET_NOT_READY;
    const auto key_bytes = manifest->copied_keys_bytes;
    const auto payload_bytes = manifest->copied_payload_bytes;
    if (keys_capacity < key_bytes || payload_capacity < payload_bytes) {
      return FA_PACKET_BUFFER_TOO_SMALL;
    }
    if (keys_buffer == nullptr || payload_buffer == nullptr ||
        Overlap(keys_buffer, key_bytes, payload_buffer, payload_bytes) ||
        Overlap(keys_buffer, key_bytes, manifest, sizeof(*manifest)) ||
        Overlap(payload_buffer, payload_bytes, manifest, sizeof(*manifest)) ||
        Overlap(keys_buffer, key_bytes, keys_.data(), keys_.size()) ||
        Overlap(keys_buffer, key_bytes, payload_.data(), payload_.size()) ||
        Overlap(payload_buffer, payload_bytes, keys_.data(), keys_.size()) ||
        Overlap(payload_buffer, payload_bytes, payload_.data(), payload_.size())) {
      return FA_PACKET_INVALID_ARGUMENT;
    }
    std::memcpy(keys_buffer, keys_.data(), static_cast<size_t>(key_bytes));
    std::memcpy(payload_buffer, payload_.data(),
                static_cast<size_t>(payload_bytes));
    return FA_PACKET_OK;
  } catch (...) {
    return FA_PACKET_CONTROL_EXCEPTION;
  }
}

int PacketCapture::RequestCancellation() noexcept {
  auto state = state_.load(std::memory_order_acquire);
  for (;;) {
    if (state == FA_PACKET_IDLE) return FA_PACKET_NO_CAPTURE;
    if (state == FA_PACKET_READY) return FA_PACKET_ALREADY_READY;
    if (state == FA_PACKET_CANCELLED) return FA_PACKET_CANCELLED_RESULT;
    if (state == FA_PACKET_CANCELLING) return FA_PACKET_CANCEL_PENDING;
    const auto desired = state == FA_PACKET_WRITING ? FA_PACKET_CANCELLING
                                                    : FA_PACKET_CANCELLED;
    if (state_.compare_exchange_strong(state, desired, std::memory_order_acq_rel,
                                        std::memory_order_acquire)) {
      last_skip_reason_.store(FA_PACKET_SKIP_CANCELLED,
                              std::memory_order_relaxed);
      return desired == FA_PACKET_CANCELLING ? FA_PACKET_CANCEL_PENDING
                                             : FA_PACKET_OK;
    }
  }
}

int PacketCapture::Cancel(uint32_t version, uint64_t capture_id) noexcept {
  if (version != FA_PACKET_ABI_VERSION) return FA_PACKET_UNSUPPORTED_VERSION;
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    const auto result = CheckCaptureIdLocked(capture_id);
    return result == FA_PACKET_OK ? RequestCancellation() : result;
  } catch (...) {
    return FA_PACKET_CONTROL_EXCEPTION;
  }
}

int PacketCapture::Release(uint32_t version, uint64_t capture_id) noexcept {
  if (version != FA_PACKET_ABI_VERSION) return FA_PACKET_UNSUPPORTED_VERSION;
  try {
    std::lock_guard<std::mutex> lock(control_mutex_);
    const auto result = CheckCaptureIdLocked(capture_id);
    if (result != FA_PACKET_OK) return result;
    const auto state = state_.load(std::memory_order_acquire);
    if (state != FA_PACKET_READY && state != FA_PACKET_CANCELLED) {
      return FA_PACKET_BUSY;
    }
    std::fill(keys_.begin(), keys_.end(), 0);
    std::fill(payload_.begin(), payload_.end(), 0);
    captured_ = {};
    request_ = {};
    active_id_ = 0;
    checked_packets_.store(0, std::memory_order_relaxed);
    skipped_packets_.store(0, std::memory_order_relaxed);
    last_skip_reason_.store(FA_PACKET_SKIP_NONE, std::memory_order_relaxed);
    state_.store(FA_PACKET_IDLE, std::memory_order_release);
    return FA_PACKET_OK;
  } catch (...) {
    return FA_PACKET_CONTROL_EXCEPTION;
  }
}

}  // namespace fa
