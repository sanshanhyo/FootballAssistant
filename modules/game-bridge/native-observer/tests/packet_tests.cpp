#include "fa_native_packet.h"
#include "observer_core.hpp"
#include "packet_capture.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>
#include <vector>

#if defined(__APPLE__)
#include <sys/mman.h>
#include <unistd.h>
#endif

namespace {
struct Header { const void *data; uint64_t count; };
static_assert(sizeof(Header) == 16 && offsetof(Header, count) == 8);

void Check(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

fa_packet_request_v1 Request(uint32_t minimum_payload = 64) {
  fa_packet_request_v1 request{};
  Check(fa::PacketCapture::DefaultRequest(&request, sizeof(request)) == FA_PACKET_OK,
        "default request failed");
  request.min_payload_bytes = minimum_payload;
  return request;
}

fa_packet_manifest_v1 Manifest(fa::PacketCapture &capture,
                               const std::atomic<uint32_t> &enabled,
                               uint64_t id = 0) {
  fa_packet_manifest_v1 result{};
  Check(capture.GetManifest(1, id, enabled, &result, sizeof(result)) == FA_PACKET_OK,
        "manifest query failed");
  return result;
}

uint64_t Arm(fa::PacketCapture &capture, const fa_packet_request_v1 &request,
              const std::atomic<uint32_t> &enabled) {
  uint64_t id = 0;
  Check(capture.Arm(&request, sizeof(request), enabled, &id) == FA_PACKET_OK && id != 0,
        "arm failed");
  return id;
}

void TestOwnedCopyAndRelease() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  auto request = Request();
  auto keys = std::make_unique<uint64_t[]>(4);
  auto payload = std::make_unique<unsigned char[]>(256);
  std::array<uint64_t, 4> expected_keys{1, 0xfedcba9876543210ULL, 3, 4};
  std::array<unsigned char, 256> expected_payload{};
  for (size_t i = 0; i < expected_payload.size(); ++i) {
    expected_payload[i] = static_cast<unsigned char>(i ^ 0x5a);
  }
  std::memcpy(keys.get(), expected_keys.data(), sizeof(expected_keys));
  std::memcpy(payload.get(), expected_payload.data(), expected_payload.size());
  Header key_header{keys.get(), 4};
  Header payload_header{payload.get(), 256};
  capture.TryCapture(1, &key_header, &payload_header);
  Check(Manifest(capture, enabled).state == FA_PACKET_IDLE,
        "capture must default off");
  const auto id = Arm(capture, request, enabled);
  std::array<uint64_t, 4> output_keys{};
  std::array<unsigned char, 256> output_payload{};
  fa_packet_manifest_v1 manifest{};
  Check(capture.Copy(1, id, output_keys.data(), sizeof(output_keys),
                       output_payload.data(), output_payload.size(), enabled,
                       &manifest, sizeof(manifest)) == FA_PACKET_NOT_READY,
        "unwritten capture must not be readable");
  capture.TryCapture(7, &key_header, &payload_header);
  std::memset(keys.get(), 0, sizeof(expected_keys));
  std::memset(payload.get(), 0, expected_payload.size());
  keys.reset();
  payload.reset();
  /* The source data is now freed. READY must not look at it again. */
  capture.TryCapture(8, &key_header, &payload_header);
  manifest = Manifest(capture, enabled, id);
  Check(manifest.state == FA_PACKET_READY && manifest.flags == 7 &&
            manifest.call_sequence == 7 && manifest.capture_id == id &&
            manifest.original_keys_count == 4 &&
            manifest.original_payload_count == 256 &&
            manifest.copied_keys_bytes == 32 &&
            manifest.copied_payload_bytes == 256,
        "ready manifest differs from complete packet");
  output_keys.fill(UINT64_MAX);
  output_payload.fill(0xff);
  Check(capture.Copy(1, id, output_keys.data(), 8, output_payload.data(),
                       output_payload.size(), enabled, &manifest,
                       sizeof(manifest)) == FA_PACKET_BUFFER_TOO_SMALL &&
            output_keys[0] == UINT64_MAX && output_payload[0] == 0xff,
        "small caller buffers must not be partly copied");
  Check(capture.Copy(1, id, output_keys.data(), sizeof(output_keys),
                       output_payload.data(), output_payload.size(), enabled,
                       &manifest, sizeof(manifest)) == FA_PACKET_OK &&
            output_keys == expected_keys && output_payload == expected_payload,
        "owned snapshot changed after original buffers were freed");
  uint64_t new_id = 0;
  Check(capture.Arm(&request, sizeof(request), enabled, &new_id) ==
            FA_PACKET_NEEDS_RELEASE && new_id == 0,
        "ready snapshot must not be overwritten by rearm");
  Check(capture.Cancel(1, id) == FA_PACKET_ALREADY_READY,
        "cancel must preserve an already ready snapshot");
  Check(capture.Release(1, id + 1) == FA_PACKET_WRONG_CAPTURE_ID,
        "wrong release ID accepted");
  Check(capture.Release(1, id) == FA_PACKET_OK &&
            capture.Copy(1, id, output_keys.data(), sizeof(output_keys),
                           output_payload.data(), output_payload.size(), enabled,
                           &manifest, sizeof(manifest)) == FA_PACKET_NO_CAPTURE,
        "released snapshot still readable");
  const auto second_id = Arm(capture, request, enabled);
  Check(second_id > id, "capture IDs were reused");
  Check(capture.Cancel(1, second_id) == FA_PACKET_OK &&
            capture.Release(1, second_id) == FA_PACKET_OK,
        "cancelled slot could not be released");
}

void TestBoundsAndUnknowns() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  auto request = Request();
  request.max_keys = 4;
  request.max_payload_bytes = 128;
  request.max_total_bytes = 144;
  const auto id = Arm(capture, request, enabled);
  std::array<uint64_t, 4> keys{};
  std::array<unsigned char, 129> payload{};
  Header kh{keys.data(), 1};
  Header ph{payload.data(), 64};
  uint64_t sequence = 1;
  auto reject = [&](const void *key_header, const void *payload_header,
                    uint32_t reason) {
    capture.TryCapture(sequence++, key_header, payload_header);
    const auto state = Manifest(capture, enabled, id);
    Check(state.state == FA_PACKET_ARMED &&
              (state.flags & FA_PACKET_COUNTS_KNOWN) == 0 &&
              state.copied_keys_bytes == 0 && state.copied_payload_bytes == 0 &&
              state.last_skip_reason == reason,
          "rejected packet became complete or lost its explicit skip reason");
  };
  reject(nullptr, &ph, FA_PACKET_SKIP_NULL_HEADER);
  kh.count = 0;
  reject(&kh, &ph, FA_PACKET_SKIP_KEYS_BELOW_MINIMUM);
  kh.count = 1;
  ph.count = 0;
  reject(&kh, &ph, FA_PACKET_SKIP_PAYLOAD_BELOW_MINIMUM);
  ph.count = 64;
  kh.count = UINT64_MAX;
  reject(&kh, &ph, FA_PACKET_SKIP_KEYS_SIZE_OVERFLOW);
  kh.count = 5;
  reject(&kh, &ph, FA_PACKET_SKIP_KEYS_OVER_CAP);
  kh.count = 1;
  ph.count = 129;
  reject(&kh, &ph, FA_PACKET_SKIP_PAYLOAD_OVER_CAP);
  kh.count = 4;
  ph.count = 128;
  reject(&kh, &ph, FA_PACKET_SKIP_TOTAL_OVER_CAP);
  kh.count = 1;
  ph.count = 64;
  kh.data = nullptr;
  reject(&kh, &ph, FA_PACKET_SKIP_NULL_KEYS_DATA);
  kh.data = keys.data();
  ph.data = nullptr;
  reject(&kh, &ph, FA_PACKET_SKIP_NULL_PAYLOAD_DATA);
  ph.data = payload.data();
  capture.TryCapture(sequence, &kh, &ph);
  const auto ready = Manifest(capture, enabled, id);
  Check(ready.state == FA_PACKET_READY && ready.checked_packets == 10 &&
            ready.skipped_packets == 9 && ready.original_payload_count == 64 &&
            ready.last_skip_reason == FA_PACKET_SKIP_NONE,
        "valid candidate did not follow skipped candidates");
}

void TestFullCapAndControlValidation() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  auto request = Request();
  auto invalid = request;
  uint64_t id = 99;
  invalid.version = 99;
  Check(capture.Arm(&invalid, sizeof(invalid), enabled, &id) ==
            FA_PACKET_UNSUPPORTED_VERSION && id == 0,
        "unknown packet version accepted");
  invalid = request;
  invalid.flags = 1;
  Check(capture.Arm(&invalid, sizeof(invalid), enabled, &id) ==
            FA_PACKET_INVALID_ARGUMENT,
        "unknown request flag accepted");
  invalid = request;
  invalid.max_payload_bytes = 65537;
  Check(capture.Arm(&invalid, sizeof(invalid), enabled, &id) ==
            FA_PACKET_INVALID_ARGUMENT,
        "payload cap larger than owned storage accepted");
  invalid = request;
  invalid.max_total_bytes = 8;
  Check(capture.Arm(&invalid, sizeof(invalid), enabled, &id) ==
            FA_PACKET_INVALID_ARGUMENT,
        "impossible minimum/total combination accepted");
  Check(capture.Arm(&request, sizeof(request) - 1, enabled, &id) ==
            FA_PACKET_BUFFER_TOO_SMALL,
        "small request accepted");
  std::vector<uint64_t> keys(4096, 0xabcdef9876543210ULL);
  std::vector<unsigned char> payload(65536, 0x7b);
  Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
  id = Arm(capture, request, enabled);
  capture.TryCapture(5, &kh, &ph);
  auto manifest = Manifest(capture, enabled, id);
  Check(manifest.copied_keys_bytes + manifest.copied_payload_bytes == 98304 &&
            manifest.state == FA_PACKET_READY,
        "exact full cap packet was truncated or rejected");
  std::vector<uint64_t> copied_keys(keys.size());
  std::vector<unsigned char> copied_payload(payload.size());
  Check(capture.Copy(2, id, copied_keys.data(), 32768, copied_payload.data(),
                       65536, enabled, &manifest, sizeof(manifest)) ==
            FA_PACKET_UNSUPPORTED_VERSION,
        "unknown copy version accepted");
  Check(capture.Copy(1, id + 1, copied_keys.data(), 32768, copied_payload.data(),
                       65536, enabled, &manifest, sizeof(manifest)) ==
            FA_PACKET_WRONG_CAPTURE_ID,
        "wrong copy ID accepted");
  Check(capture.Copy(1, id, copied_payload.data(), 32768, copied_payload.data(),
                       65536, enabled, &manifest, sizeof(manifest)) ==
            FA_PACKET_INVALID_ARGUMENT,
        "overlapping caller output accepted");
  Check(capture.Copy(1, id, copied_keys.data(), 32768, copied_payload.data(),
                       65536, enabled, &manifest, sizeof(manifest)) ==
                FA_PACKET_OK && copied_keys == keys && copied_payload == payload,
        "full cap output differs from source");
}

void TestCancelStopAndRearm() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  auto request = Request();
  auto id = Arm(capture, request, enabled);
  Check(capture.Release(1, id) == FA_PACKET_BUSY &&
            capture.Cancel(1, id + 1) == FA_PACKET_WRONG_CAPTURE_ID,
        "pending snapshot released or wrong cancellation accepted");
  Check(capture.Cancel(1, id) == FA_PACKET_OK &&
            Manifest(capture, enabled, id).state == FA_PACKET_CANCELLED,
        "armed cancellation failed");
  uint64_t next = 0;
  Check(capture.Arm(&request, sizeof(request), enabled, &next) ==
            FA_PACKET_NEEDS_RELEASE,
        "cancelled capture silently rearmed without release");
  Check(capture.Release(1, id) == FA_PACKET_OK, "cancel release failed");
  id = Arm(capture, request, enabled);
  capture.SetLegacyCaptureEnabled(enabled, false);
  auto status = Manifest(capture, enabled, id);
  Check(status.state == FA_PACKET_CANCELLED &&
            (status.flags & FA_PACKET_LEGACY_DISABLED) != 0,
        "legacy stop did not cancel pending capture");
  Check(capture.Release(1, id) == FA_PACKET_OK &&
            capture.Arm(&request, sizeof(request), enabled, &next) ==
                FA_PACKET_LEGACY_CAPTURE_DISABLED,
        "packet armed while legacy capture disabled");
  capture.SetLegacyCaptureEnabled(enabled, true);
  id = Arm(capture, request, enabled);
  std::array<uint64_t, 1> keys{7};
  std::array<unsigned char, 64> payload{};
  Header kh{keys.data(), 1}, ph{payload.data(), payload.size()};
  capture.TryCapture(1, &kh, &ph);
  capture.SetLegacyCaptureEnabled(enabled, false);
  status = Manifest(capture, enabled, id);
  Check(status.state == FA_PACKET_READY &&
            (status.flags & (FA_PACKET_COMPLETE | FA_PACKET_LEGACY_DISABLED)) ==
                (FA_PACKET_COMPLETE | FA_PACKET_LEGACY_DISABLED),
        "stop discarded an already ready packet");
}

void TestUnreadableAndOverflowRanges() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  const auto request = Request();
  const auto id = Arm(capture, request, enabled);
  std::array<uint64_t, 2> keys{};
  std::array<unsigned char, 128> payload{};
  Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
  auto reject = [&](uint32_t reason) {
    capture.TryCapture(1, &kh, &ph);
    const auto manifest = Manifest(capture, enabled, id);
    Check(manifest.state == FA_PACKET_ARMED &&
              (manifest.flags & FA_PACKET_COMPLETE) == 0 &&
              manifest.last_skip_reason == reason,
          "unreadable/overflow source was published as a complete packet");
  };
  kh.data = reinterpret_cast<void *>(UINTPTR_MAX - 3);
  reject(FA_PACKET_SKIP_SOURCE_RANGE_OVERFLOW);
  kh.data = reinterpret_cast<void *>(uintptr_t{1});
  reject(FA_PACKET_SKIP_UNREADABLE_KEYS);
  kh.data = keys.data();
  ph.data = reinterpret_cast<void *>(uintptr_t{1});
  reject(FA_PACKET_SKIP_UNREADABLE_PAYLOAD);
#if defined(__APPLE__)
  const auto page_size = static_cast<size_t>(sysconf(_SC_PAGESIZE));
  auto *pages = static_cast<unsigned char *>(mmap(
      nullptr, page_size * 2, PROT_READ | PROT_WRITE,
      MAP_PRIVATE | MAP_ANON, -1, 0));
  Check(pages != MAP_FAILED, "protected source fixture allocation failed");
  Check(mprotect(pages + page_size, page_size, PROT_NONE) == 0,
        "protected source fixture setup failed");
  ph.data = pages + page_size - 32;
  ph.count = 64;
  reject(FA_PACKET_SKIP_UNREADABLE_PAYLOAD);
  Check(munmap(pages, page_size * 2) == 0,
        "protected source fixture cleanup failed");
#endif
  ph.data = payload.data();
  ph.count = payload.size();
  capture.TryCapture(9, &kh, &ph);
  Check(Manifest(capture, enabled, id).state == FA_PACKET_READY,
        "skipped invalid ranges prevented a later valid complete packet");
}

uint64_t latency_p50_ns = 0, latency_p95_ns = 0, latency_max_ns = 0;

void TestBoundedCopyLatency() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  const auto request = Request();
  std::vector<uint64_t> keys(4096, 42);
  std::vector<unsigned char> payload(65536, 0x5a);
  Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
  std::vector<uint64_t> durations;
  for (unsigned i = 0; i < 31; ++i) {
    const auto id = Arm(capture, request, enabled);
    const auto start = fa::MonotonicNanosecondsForControl();
    capture.TryCapture(i + 1, &kh, &ph);
    durations.push_back(fa::MonotonicNanosecondsForControl() - start);
    Check(Manifest(capture, enabled, id).state == FA_PACKET_READY,
          "full-size latency fixture did not copy completely");
    Check(capture.Release(1, id) == FA_PACKET_OK, "latency fixture release failed");
  }
  std::sort(durations.begin(), durations.end());
  latency_p50_ns = durations[durations.size() / 2];
  latency_p95_ns = durations[durations.size() * 95 / 100];
  latency_max_ns = durations.back();
}

void FillPattern(unsigned char *payload, size_t size, uint64_t producer,
                   uint64_t sequence) {
  for (size_t i = 0; i < size; ++i) {
    payload[i] = static_cast<unsigned char>((producer * 31 + sequence + i) & 255);
  }
}

bool ValidPattern(const uint64_t *keys, const unsigned char *payload, size_t size) {
  if (keys[0] >= 8) return false;
  for (size_t i = 0; i < size; ++i) {
    if (payload[i] != static_cast<unsigned char>(
                          (keys[0] * 31 + keys[1] + i) & 255)) return false;
  }
  return true;
}

void TestConcurrentSingleWinner() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  const auto request = Request();
  const auto id = Arm(capture, request, enabled);
  std::atomic<unsigned> ready{0};
  std::atomic<bool> start{false};
  std::vector<std::thread> producers;
  for (uint64_t producer = 0; producer < 8; ++producer) {
    producers.emplace_back([&, producer] {
      std::array<uint64_t, 2> keys{producer, 12345 + producer};
      std::array<unsigned char, 128> payload{};
      FillPattern(payload.data(), payload.size(), keys[0], keys[1]);
      Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
      ready.fetch_add(1, std::memory_order_release);
      while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
      for (unsigned i = 0; i < 100; ++i) {
        capture.TryCapture(producer + 1, &kh, &ph);
      }
      payload.fill(0);
      keys.fill(0);
    });
  }
  while (ready.load(std::memory_order_acquire) != 8) std::this_thread::yield();
  start.store(true, std::memory_order_release);
  for (auto &producer : producers) producer.join();
  std::array<uint64_t, 2> keys{};
  std::array<unsigned char, 128> payload{};
  fa_packet_manifest_v1 manifest{};
  Check(capture.Copy(1, id, keys.data(), sizeof(keys), payload.data(), payload.size(),
                       enabled, &manifest, sizeof(manifest)) == FA_PACKET_OK &&
            manifest.checked_packets == 1 && manifest.original_keys_count == 2 &&
            ValidPattern(keys.data(), payload.data(), payload.size()),
        "competing producers published more than one or a torn snapshot");
}

void TestConcurrentControlAndCopy() {
  fa::PacketCapture capture;
  std::atomic<uint32_t> enabled{1};
  auto request = Request();
  std::atomic<bool> running{true};
  std::atomic<uint64_t> active{0}, errors{0}, copies{0};
  std::vector<std::thread> producers;
  for (uint64_t producer = 0; producer < 4; ++producer) {
    producers.emplace_back([&, producer] {
      std::array<uint64_t, 2> keys{producer, 0};
      std::array<unsigned char, 128> payload{};
      Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
      while (running.load(std::memory_order_acquire)) {
        ++keys[1];
        FillPattern(payload.data(), payload.size(), keys[0], keys[1]);
        if (enabled.load(std::memory_order_acquire) != 0) {
          capture.TryCapture(keys[1], &kh, &ph);
        }
      }
    });
  }
  std::thread consumer([&] {
    std::array<uint64_t, 2> keys{};
    std::array<unsigned char, 128> payload{};
    fa_packet_manifest_v1 manifest{};
    while (running.load(std::memory_order_acquire)) {
      const auto id = active.load(std::memory_order_acquire);
      if (id == 0) { std::this_thread::yield(); continue; }
      const auto result = capture.Copy(1, id, keys.data(), sizeof(keys),
                                       payload.data(), payload.size(), enabled,
                                       &manifest, sizeof(manifest));
      if (result == FA_PACKET_OK) {
        if (manifest.capture_id != id || manifest.original_keys_count != 2 ||
            manifest.original_payload_count != 128 ||
            !ValidPattern(keys.data(), payload.data(), payload.size())) {
          errors.fetch_add(1, std::memory_order_relaxed);
        }
        copies.fetch_add(1, std::memory_order_relaxed);
      } else if (result != FA_PACKET_NOT_READY &&
                 result != FA_PACKET_WRONG_CAPTURE_ID &&
                 result != FA_PACKET_NO_CAPTURE &&
                 result != FA_PACKET_CANCELLED_RESULT) {
        errors.fetch_add(1, std::memory_order_relaxed);
      }
    }
  });
  for (unsigned cycle = 0; cycle < 300; ++cycle) {
    capture.SetLegacyCaptureEnabled(enabled, true);
    const auto id = Arm(capture, request, enabled);
    active.store(id, std::memory_order_release);
    if (cycle % 3 == 0) capture.Cancel(1, id);
    if (cycle % 5 == 0) capture.SetLegacyCaptureEnabled(enabled, false);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    for (;;) {
      const auto state = Manifest(capture, enabled, id).state;
      if (state == FA_PACKET_READY || state == FA_PACKET_CANCELLED) break;
      Check(std::chrono::steady_clock::now() < deadline,
            "concurrent cancellation/capture did not reach a terminal state");
      std::this_thread::yield();
    }
    for (unsigned i = 0; i < 10; ++i) std::this_thread::yield();
    Check(capture.Release(1, id) == FA_PACKET_OK,
          "terminal snapshot could not be released concurrently with copying");
    active.store(0, std::memory_order_release);
  }
  running.store(false, std::memory_order_release);
  for (auto &producer : producers) producer.join();
  consumer.join();
  Check(errors == 0 && copies != 0 &&
            Manifest(capture, enabled).state == FA_PACKET_IDLE,
        "control/copy race returned a torn packet or failed to rearm");
}

fa::ObserverCore *integration_core = nullptr;
std::atomic<uint64_t> original_calls{0};
bool throw_original = false;
struct Marker { int value; };
void Original(void *, const void *, const void *) {
  original_calls.fetch_add(1, std::memory_order_relaxed);
  if (throw_original) throw Marker{27};
}
void Replacement(void *receiver, const void *keys, const void *payload) {
  integration_core->Forward(receiver, keys, payload);
}
int Prepare(void *, void *, void **original) {
  *original = reinterpret_cast<void *>(&Original);
  return 0;
}
int Commit(void *) { return 0; }

void TestForwardingAndExceptionIntegration() {
  fa::ObserverCore core;
  integration_core = &core;
  fa_observer_install_report report{};
  Check(core.PrepareAndCommit(reinterpret_cast<void *>(uintptr_t{0x1234}),
                               reinterpret_cast<void *>(&Replacement), &Prepare,
                               &Commit, report) == FA_OBSERVER_OK,
        "integration install failed");
  Check(core.StartCapture() == FA_OBSERVER_OK, "integration start failed");
  auto request = Request();
  uint64_t id = 0;
  Check(core.ArmPacket(&request, sizeof(request), &id) == FA_PACKET_OK,
        "integration arm failed");
  std::array<uint64_t, 2> keys{3, 4};
  std::array<unsigned char, 128> payload{};
  Header kh{keys.data(), keys.size()}, ph{payload.data(), payload.size()};
  core.Forward(nullptr, &kh, &ph);
  Check(original_calls == 1, "packet copy changed original invocation count");
  Check(core.ReleasePacket(1, id) == FA_PACKET_OK &&
            core.ArmPacket(&request, sizeof(request), &id) == FA_PACKET_OK,
        "integration rearm failed");
  throw_original = true;
  bool caught = false;
  try { core.Forward(nullptr, &kh, &ph); }
  catch (const Marker &marker) { caught = marker.value == 27; }
  throw_original = false;
  fa_packet_manifest_v1 manifest{};
  Check(caught && original_calls == 2 &&
            core.GetPacketManifest(1, id, &manifest, sizeof(manifest)) == FA_PACKET_OK &&
            manifest.state == FA_PACKET_READY &&
            (manifest.flags & FA_PACKET_ORIGINAL_RESULT_UNKNOWN) != 0,
        "packet capture swallowed original exception or claimed receiver success");
  Check(core.ReleasePacket(1, id) == FA_PACKET_OK &&
            core.ArmPacket(&request, sizeof(request), &id) == FA_PACKET_OK,
        "integration final arm failed");
  core.StopCapture();
  core.Forward(nullptr, &kh, &ph);
  Check(original_calls == 3 &&
            core.GetPacketManifest(1, id, &manifest, sizeof(manifest)) == FA_PACKET_OK &&
            manifest.state == FA_PACKET_CANCELLED,
        "stop broke original or left pending packet capture active");
}

}  // namespace

int main() {
  try {
    TestOwnedCopyAndRelease();
    TestBoundsAndUnknowns();
    TestFullCapAndControlValidation();
    TestCancelStopAndRearm();
    TestUnreadableAndOverflowRanges();
    TestBoundedCopyLatency();
    TestConcurrentSingleWinner();
    TestConcurrentControlAndCopy();
    TestForwardingAndExceptionIntegration();
    std::cout << "{\"status\":\"passed\",\"packet_tests\":9,"
                 "\"control_cycles\":300,\"max_packet_bytes\":98304,"
                 "\"copy_latency_p50_ns\":" << latency_p50_ns
              << ",\"copy_latency_p95_ns\":" << latency_p95_ns
              << ",\"copy_latency_max_ns\":" << latency_max_ns
              << ",\"game_process_touched\":false}\n";
    return 0;
  } catch (const std::exception &exception) {
    std::cerr << "packet test failed: " << exception.what() << '\n';
    return 1;
  }
}
