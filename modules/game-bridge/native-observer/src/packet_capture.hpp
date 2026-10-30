#ifndef FA_PACKET_CAPTURE_HPP
#define FA_PACKET_CAPTURE_HPP

#include "fa_native_packet.h"

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace fa {

uint64_t MonotonicNanosecondsForControl() noexcept;
uint64_t NativeThreadIdForCapture() noexcept;

static_assert(sizeof(fa_packet_request_v1) == 48);
static_assert(sizeof(fa_packet_manifest_v1) == 112);
static_assert(offsetof(fa_packet_manifest_v1, capture_id) == 16);
static_assert(offsetof(fa_packet_manifest_v1, checked_packets) == 80);
static_assert(offsetof(fa_packet_manifest_v1, last_skip_reason) == 96);
static_assert(offsetof(fa_packet_manifest_v1, busy_skipped_total) == 104);
static_assert(std::atomic<uint32_t>::is_always_lock_free);

class PacketCapture final {
 public:
  static int DefaultRequest(fa_packet_request_v1 *request,
                            uint32_t request_size) noexcept;
  int SetLegacyCaptureEnabled(std::atomic<uint32_t> &enabled,
                               bool value) noexcept;
  int Arm(const fa_packet_request_v1 *request, uint32_t request_size,
          const std::atomic<uint32_t> &legacy_enabled,
          uint64_t *out_capture_id) noexcept;
  void TryCapture(uint64_t call_sequence, const void *keys_header,
                   const void *payload_header) noexcept;
  int GetManifest(uint32_t version, uint64_t capture_id,
                   const std::atomic<uint32_t> &legacy_enabled,
                   fa_packet_manifest_v1 *manifest,
                   uint32_t manifest_size) noexcept;
  int Copy(uint32_t version, uint64_t capture_id, void *keys_buffer,
           uint64_t keys_capacity, void *payload_buffer,
           uint64_t payload_capacity,
           const std::atomic<uint32_t> &legacy_enabled,
           fa_packet_manifest_v1 *manifest,
           uint32_t manifest_size) noexcept;
  int Cancel(uint32_t version, uint64_t capture_id) noexcept;
  int Release(uint32_t version, uint64_t capture_id) noexcept;

 private:
  static int CheckOutput(uint32_t version, fa_packet_manifest_v1 *manifest,
                         uint32_t manifest_size) noexcept;
  int CheckCaptureIdLocked(uint64_t capture_id) const noexcept;
  void FillManifestLocked(const std::atomic<uint32_t> &legacy_enabled,
                            fa_packet_manifest_v1 &manifest) const noexcept;
  int RequestCancellation() noexcept;
  void FinishSkipped(uint32_t reason) noexcept;
  void FinishCancelled() noexcept;

  /* Only control-plane operations take this mutex. TryCapture never does. */
  mutable std::mutex control_mutex_;
  std::atomic<uint32_t> state_{FA_PACKET_IDLE};
  fa_packet_request_v1 request_{};
  uint64_t active_id_{0};
  uint64_t last_assigned_id_{0};
  fa_packet_manifest_v1 captured_{};
  std::atomic<uint64_t> checked_packets_{0};
  std::atomic<uint64_t> skipped_packets_{0};
  std::atomic<uint64_t> busy_skipped_total_{0};
  std::atomic<uint32_t> last_skip_reason_{FA_PACKET_SKIP_NONE};
  alignas(64) std::array<unsigned char, FA_PACKET_MAX_KEYS * 8> keys_{};
  alignas(64) std::array<unsigned char, FA_PACKET_MAX_PAYLOAD_BYTES> payload_{};
};

}  // namespace fa
#endif
