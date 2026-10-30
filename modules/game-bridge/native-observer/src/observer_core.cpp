#include "observer_core.hpp"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <limits>

#if defined(__APPLE__)
#include <pthread.h>
#elif defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#elif defined(__linux__)
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace fa {
namespace {

uint64_t NativeThreadId() noexcept {
#if defined(__APPLE__)
  uint64_t result = 0;
  return pthread_threadid_np(nullptr, &result) == 0 ? result : 0;
#elif defined(_WIN32)
  return static_cast<uint64_t>(GetCurrentThreadId());
#elif defined(__linux__)
  return static_cast<uint64_t>(syscall(SYS_gettid));
#else
  return 0;
#endif
}

uint64_t MonotonicNanoseconds() noexcept {
  const auto value = std::chrono::duration_cast<std::chrono::nanoseconds>(
                         std::chrono::steady_clock::now().time_since_epoch())
                         .count();
  return value >= 0 ? static_cast<uint64_t>(value) : 0;
}

struct InFlightGuard final {
  explicit InFlightGuard(std::atomic<uint64_t> &value) noexcept : value_(value) {
    value_.fetch_add(1, std::memory_order_relaxed);
  }
  ~InFlightGuard() noexcept {
    value_.fetch_sub(1, std::memory_order_relaxed);
  }
  std::atomic<uint64_t> &value_;
};

}  // namespace

uint64_t MonotonicNanosecondsForControl() noexcept {
  return MonotonicNanoseconds();
}

uint64_t NativeThreadIdForCapture() noexcept { return NativeThreadId(); }

RecordQueue::RecordQueue() noexcept {
  for (uint64_t index = 0; index < kCapacity; ++index) {
    slots_[index].sequence.store(index, std::memory_order_relaxed);
  }
}

QueueResult RecordQueue::Push(const fa_observer_record &record) noexcept {
  uint64_t position = enqueue_position_.load(std::memory_order_relaxed);
  for (unsigned attempt = 0; attempt < kAttempts; ++attempt) {
    Slot &slot = slots_[position & (kCapacity - 1)];
    const auto sequence = slot.sequence.load(std::memory_order_acquire);
    const auto difference = static_cast<int64_t>(sequence - position);
    if (difference == 0) {
      if (enqueue_position_.compare_exchange_weak(
              position, position + 1, std::memory_order_relaxed)) {
        slot.record = record;
        slot.sequence.store(position + 1, std::memory_order_release);
        return QueueResult::success;
      }
    } else if (difference < 0) {
      return QueueResult::full;
    } else {
      position = enqueue_position_.load(std::memory_order_relaxed);
    }
  }
  return QueueResult::contention;
}

bool RecordQueue::Pop(fa_observer_record &record) noexcept {
  uint64_t position = dequeue_position_.load(std::memory_order_relaxed);
  for (unsigned attempt = 0; attempt < kAttempts; ++attempt) {
    Slot &slot = slots_[position & (kCapacity - 1)];
    const auto sequence = slot.sequence.load(std::memory_order_acquire);
    const auto difference = static_cast<int64_t>(sequence - (position + 1));
    if (difference == 0) {
      if (dequeue_position_.compare_exchange_weak(
              position, position + 1, std::memory_order_relaxed)) {
        record = slot.record;
        slot.sequence.store(position + kCapacity, std::memory_order_release);
        return true;
      }
    } else if (difference < 0) {
      return false;
    } else {
      position = dequeue_position_.load(std::memory_order_relaxed);
    }
  }
  return false;
}

uint64_t RecordQueue::ApproximateSize() const noexcept {
  const auto enqueued = enqueue_position_.load(std::memory_order_relaxed);
  const auto dequeued = dequeue_position_.load(std::memory_order_relaxed);
  const auto size = enqueued - dequeued;
  return size > kCapacity ? kCapacity : size;
}

int ObserverCore::PrepareAndCommit(void *target, void *replacement,
                                 PrepareFunction prepare, CommitFunction commit,
                                 fa_observer_install_report &report) noexcept {
  if (target == nullptr || replacement == nullptr || target == replacement ||
      prepare == nullptr || commit == nullptr) {
    return FA_OBSERVER_INVALID_ARGUMENT;
  }
  uint32_t expected_state = FA_OBSERVER_UNINSTALLED;
  if (!install_state_.compare_exchange_strong(
          expected_state, FA_OBSERVER_INSTALLING, std::memory_order_acq_rel)) {
    return expected_state == FA_OBSERVER_COMMITTED
               ? FA_OBSERVER_ALREADY_INSTALLED
               : FA_OBSERVER_INSTALL_NOT_RETRYABLE;
  }

  try {
    void *original = nullptr;
    report.prepare_result = prepare(target, replacement, &original);
    if (report.prepare_result != 0) {
      install_state_.store(FA_OBSERVER_PREPARATION_FAILED,
                           std::memory_order_release);
      return FA_OBSERVER_PREPARE_FAILED;
    }
    if (original == nullptr || original == target || original == replacement) {
      install_state_.store(FA_OBSERVER_PREPARATION_FAILED,
                           std::memory_order_release);
      return FA_OBSERVER_INVALID_ORIGINAL;
    }

    original_.store(reinterpret_cast<ForwardFunction>(original),
                    std::memory_order_release);
    report.original_address = reinterpret_cast<uintptr_t>(original);
    report.checks |= FA_CHECK_ORIGINAL_PUBLISHED;
    install_state_.store(FA_OBSERVER_PREPARED, std::memory_order_release);
    report.commit_result = commit(target);
    if (report.commit_result != 0) {
      install_state_.store(FA_OBSERVER_COMMIT_FAILED_STATE,
                           std::memory_order_release);
      return FA_OBSERVER_COMMIT_FAILED;
    }
    install_state_.store(FA_OBSERVER_COMMITTED, std::memory_order_release);
    return FA_OBSERVER_OK;
  } catch (...) {
    capture_enabled_.store(0, std::memory_order_release);
    install_state_.store(original_.load(std::memory_order_acquire) == nullptr
                             ? FA_OBSERVER_PREPARATION_FAILED
                             : FA_OBSERVER_COMMIT_FAILED_STATE,
                         std::memory_order_release);
    return FA_OBSERVER_CONTROL_EXCEPTION;
  }
}

void ObserverCore::Forward(void *receiver, const void *keys, const void *payload) {
  const auto original = original_.load(std::memory_order_acquire);
  /* Commit cannot happen until this pointer has been published. Never silently
   * swallow a business callback if this internal installation invariant breaks.
   */
  if (original == nullptr) {
    std::abort();
  }
  InFlightGuard in_flight(in_flight_);
  const auto sequence =
      invocation_count_.fetch_add(1, std::memory_order_relaxed) + 1;
  if (capture_enabled_.load(std::memory_order_acquire) != 0) {
    Capture(sequence, keys, payload);
    packet_.TryCapture(sequence, keys, payload);
  } else {
    stopped_invocations_.fetch_add(1, std::memory_order_relaxed);
  }

  /* Deliberately outside a catch and deliberately not noexcept: an original
   * C++ exception keeps its native unwind path. There is no managed callback.
   */
  original(receiver, keys, payload);
}

void ObserverCore::Capture(uint64_t sequence, const void *keys,
                           const void *payload) noexcept {
  fa_observer_record record{};
  record.call_sequence = sequence;
  record.monotonic_ns = MonotonicNanoseconds();
  record.native_thread_id = NativeThreadId();
  if (record.native_thread_id == 0) {
    record.flags |= FA_RECORD_THREAD_ID_UNKNOWN;
  }
  if (keys != nullptr) {
    std::memcpy(&record.keys_count,
                static_cast<const unsigned char *>(keys) + 8, sizeof(uint64_t));
    record.flags |= FA_RECORD_KEYS_COUNT_KNOWN;
    if (record.keys_count > static_cast<uint64_t>(INT32_MAX)) {
      record.flags |= FA_RECORD_KEYS_COUNT_EXCEEDS_INT32;
    }
    if (record.keys_count > std::numeric_limits<uint64_t>::max() / 8) {
      record.flags |= FA_RECORD_KEYS_BYTE_SIZE_OVERFLOW;
    }
  }
  if (payload != nullptr) {
    std::memcpy(&record.payload_count,
                static_cast<const unsigned char *>(payload) + 8,
                sizeof(uint64_t));
    record.flags |= FA_RECORD_PAYLOAD_COUNT_KNOWN;
    if (record.payload_count > static_cast<uint64_t>(INT32_MAX)) {
      record.flags |= FA_RECORD_PAYLOAD_COUNT_EXCEEDS_INT32;
    }
  }

  switch (queue_.Push(record)) {
    case QueueResult::success:
      enqueued_count_.fetch_add(1, std::memory_order_relaxed);
      break;
    case QueueResult::full:
      overflow_dropped_.fetch_add(1, std::memory_order_relaxed);
      break;
    case QueueResult::contention:
      contention_dropped_.fetch_add(1, std::memory_order_relaxed);
      break;
  }
}

int ObserverCore::StartCapture() noexcept {
  if (install_state_.load(std::memory_order_acquire) != FA_OBSERVER_COMMITTED) {
    return FA_OBSERVER_NOT_INSTALLED;
  }
  return packet_.SetLegacyCaptureEnabled(capture_enabled_, true);
}

void ObserverCore::StopCapture() noexcept {
  packet_.SetLegacyCaptureEnabled(capture_enabled_, false);
}

void ObserverCore::RejectUnverifiedPatch() noexcept {
  StopCapture();
  install_state_.store(FA_OBSERVER_COMMIT_FAILED_STATE,
                       std::memory_order_release);
}

uint32_t ObserverCore::Drain(fa_observer_record *records,
                            uint32_t capacity) noexcept {
  uint32_t result = 0;
  while (result < capacity && queue_.Pop(records[result])) {
    ++result;
  }
  drained_count_.fetch_add(result, std::memory_order_relaxed);
  return result;
}

void ObserverCore::GetStats(fa_observer_stats &stats) const noexcept {
  stats = {};
  stats.abi_version = FA_OBSERVER_ABI_VERSION;
  stats.struct_size = sizeof(stats);
  stats.install_state = install_state_.load(std::memory_order_acquire);
  stats.capture_enabled = capture_enabled_.load(std::memory_order_acquire);
  stats.invocation_count = invocation_count_.load(std::memory_order_relaxed);
  stats.enqueued_count = enqueued_count_.load(std::memory_order_relaxed);
  stats.drained_count = drained_count_.load(std::memory_order_relaxed);
  stats.overflow_dropped = overflow_dropped_.load(std::memory_order_relaxed);
  stats.contention_dropped = contention_dropped_.load(std::memory_order_relaxed);
  stats.capture_stopped_invocations =
      stopped_invocations_.load(std::memory_order_relaxed);
  stats.in_flight_invocations = in_flight_.load(std::memory_order_relaxed);
  stats.queue_capacity = FA_OBSERVER_QUEUE_CAPACITY;
  stats.queue_approx_size = queue_.ApproximateSize();
}

uint32_t ObserverCore::InstallState() const noexcept {
  return install_state_.load(std::memory_order_acquire);
}

uintptr_t ObserverCore::OriginalAddress() const noexcept {
  return reinterpret_cast<uintptr_t>(original_.load(std::memory_order_acquire));
}

int ObserverCore::ArmPacket(const fa_packet_request_v1 *request,
                            uint32_t request_size,
                            uint64_t *out_capture_id) noexcept {
  if (out_capture_id != nullptr) *out_capture_id = 0;
  if (install_state_.load(std::memory_order_acquire) != FA_OBSERVER_COMMITTED) {
    return FA_PACKET_NOT_INSTALLED;
  }
  return packet_.Arm(request, request_size, capture_enabled_, out_capture_id);
}

int ObserverCore::GetPacketManifest(uint32_t version, uint64_t capture_id,
                                    fa_packet_manifest_v1 *manifest,
                                    uint32_t manifest_size) noexcept {
  return packet_.GetManifest(version, capture_id, capture_enabled_, manifest,
                              manifest_size);
}

int ObserverCore::CopyPacket(uint32_t version, uint64_t capture_id,
                             void *keys_buffer, uint64_t keys_capacity,
                             void *payload_buffer, uint64_t payload_capacity,
                             fa_packet_manifest_v1 *manifest,
                             uint32_t manifest_size) noexcept {
  return packet_.Copy(version, capture_id, keys_buffer, keys_capacity,
                      payload_buffer, payload_capacity, capture_enabled_,
                      manifest, manifest_size);
}

int ObserverCore::CancelPacket(uint32_t version, uint64_t capture_id) noexcept {
  return packet_.Cancel(version, capture_id);
}

int ObserverCore::ReleasePacket(uint32_t version, uint64_t capture_id) noexcept {
  return packet_.Release(version, capture_id);
}

}  // namespace fa
