#ifndef FA_OBSERVER_CORE_HPP
#define FA_OBSERVER_CORE_HPP

#include "fa_native_observer.h"
#include "packet_capture.hpp"

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace fa {

using ForwardFunction = void (*)(void *, const void *, const void *);
using PrepareFunction = int (*)(void *, void *, void **);
using CommitFunction = int (*)(void *);
uint64_t MonotonicNanosecondsForControl() noexcept;
uint64_t NativeThreadIdForCapture() noexcept;

static_assert(sizeof(void *) == 8, "The verified observer ABI is 64-bit only");
static_assert(sizeof(fa_observer_record) == 48);
static_assert(sizeof(fa_observer_stats) == 88);
static_assert(sizeof(fa_observer_install_report) == 48);
static_assert(offsetof(fa_observer_record, flags) == 40);
static_assert(std::atomic<uint64_t>::is_always_lock_free);
static_assert(std::atomic<ForwardFunction>::is_always_lock_free);

enum class QueueResult { success, full, contention };

/* A bounded MPMC queue. Producers perform at most eight CAS attempts; a busy
 * queue drops the diagnostic record rather than stalling the game callback.
 */
class RecordQueue final {
 public:
  RecordQueue() noexcept;
  QueueResult Push(const fa_observer_record &record) noexcept;
  bool Pop(fa_observer_record &record) noexcept;
  uint64_t ApproximateSize() const noexcept;

 private:
  static constexpr uint64_t kCapacity = FA_OBSERVER_QUEUE_CAPACITY;
  static constexpr unsigned kAttempts = 8;
  struct Slot {
    std::atomic<uint64_t> sequence{0};
    fa_observer_record record{};
  };
  std::array<Slot, kCapacity> slots_{};
  alignas(64) std::atomic<uint64_t> enqueue_position_{0};
  alignas(64) std::atomic<uint64_t> dequeue_position_{0};
};

class ObserverCore final {
 public:
  int PrepareAndCommit(void *target, void *replacement, PrepareFunction prepare,
                       CommitFunction commit,
                       fa_observer_install_report &report) noexcept;
  void Forward(void *receiver, const void *keys, const void *payload);
  int StartCapture() noexcept;
  void StopCapture() noexcept;
  void RejectUnverifiedPatch() noexcept;
  uint32_t Drain(fa_observer_record *records, uint32_t capacity) noexcept;
  void GetStats(fa_observer_stats &stats) const noexcept;
  uint32_t InstallState() const noexcept;
  uintptr_t OriginalAddress() const noexcept;
  int ArmPacket(const fa_packet_request_v1 *request, uint32_t request_size,
                 uint64_t *out_capture_id) noexcept;
  int GetPacketManifest(uint32_t version, uint64_t capture_id,
                         fa_packet_manifest_v1 *manifest,
                         uint32_t manifest_size) noexcept;
  int CopyPacket(uint32_t version, uint64_t capture_id, void *keys_buffer,
                  uint64_t keys_capacity, void *payload_buffer,
                  uint64_t payload_capacity, fa_packet_manifest_v1 *manifest,
                  uint32_t manifest_size) noexcept;
  int CancelPacket(uint32_t version, uint64_t capture_id) noexcept;
  int ReleasePacket(uint32_t version, uint64_t capture_id) noexcept;

 private:
  void Capture(uint64_t call_sequence, const void *keys,
               const void *payload) noexcept;

  std::atomic<ForwardFunction> original_{nullptr};
  std::atomic<uint32_t> install_state_{FA_OBSERVER_UNINSTALLED};
  std::atomic<uint32_t> capture_enabled_{0};
  std::atomic<uint64_t> invocation_count_{0};
  std::atomic<uint64_t> enqueued_count_{0};
  std::atomic<uint64_t> drained_count_{0};
  std::atomic<uint64_t> overflow_dropped_{0};
  std::atomic<uint64_t> contention_dropped_{0};
  std::atomic<uint64_t> stopped_invocations_{0};
  std::atomic<uint64_t> in_flight_{0};
  RecordQueue queue_{};
  PacketCapture packet_{};
};

static_assert(std::is_trivially_destructible_v<RecordQueue>);

}  // namespace fa
#endif
