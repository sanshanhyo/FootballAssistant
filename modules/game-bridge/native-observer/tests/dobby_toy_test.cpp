#include "fa_native_observer.h"
#include "fa_native_packet.h"
#include "observer_core.hpp"

#include <array>
#include <atomic>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>

#if defined(__APPLE__)
#include <dlfcn.h>
#endif

namespace {
struct SpanHeader { const void *data; uint64_t count; };
struct Marker { int value; };
std::atomic<uint64_t> original_calls{0};
std::atomic<uint64_t> argument_errors{0};
bool throw_original = false;
int receiver_value = 17;
SpanHeader keys{reinterpret_cast<void *>(uintptr_t{1}), 4};
SpanHeader payload{reinterpret_cast<void *>(uintptr_t{2}), 123};

void Check(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

#if defined(_MSC_VER)
#define FA_NOINLINE __declspec(noinline)
#else
#define FA_NOINLINE __attribute__((noinline))
#endif

/* These functions belong solely to this test executable. No FM module is
 * opened, patched, executed or inspected by this program.
 */
extern "C" FA_NOINLINE void ToyTarget(void *receiver, const void *key_header,
                                      const void *payload_header) {
#if defined(__aarch64__) || defined(__arm64__)
  asm volatile("nop\n nop\n nop\n nop\n nop\n nop\n nop\n nop\n"
               "nop\n nop\n nop\n nop\n nop\n nop\n nop\n nop\n" ::: "memory");
#endif
  original_calls.fetch_add(1, std::memory_order_relaxed);
  if (receiver != &receiver_value || key_header != &keys ||
      payload_header != &payload) {
    argument_errors.fetch_add(1, std::memory_order_relaxed);
  }
  if (throw_original) throw Marker{31415};
}

std::atomic<uint64_t> staged_original_calls{0};
std::atomic<uint64_t> staged_replacement_calls{0};
using Forward = void (*)(void *, const void *, const void *);
std::atomic<Forward> staged_original{nullptr};

extern "C" FA_NOINLINE void StagedTarget(void *, const void *, const void *) {
#if defined(__aarch64__) || defined(__arm64__)
  asm volatile("nop\n nop\n nop\n nop\n nop\n nop\n nop\n nop\n"
               "nop\n nop\n nop\n nop\n nop\n nop\n nop\n nop\n" ::: "memory");
#endif
  staged_original_calls.fetch_add(1, std::memory_order_relaxed);
}

void StagedReplacement(void *receiver, const void *key_header,
                       const void *payload_header) {
  staged_replacement_calls.fetch_add(1, std::memory_order_relaxed);
  const auto original = staged_original.load(std::memory_order_acquire);
  if (original == nullptr) std::abort();
  original(receiver, key_header, payload_header);
}

void TestOneShotThroughActualHook() {
  const std::array<uint64_t, 4> expected_keys{7, 0xfedcba9876543210ULL, 9, 10};
  std::array<unsigned char, 123> expected_payload{};
  for (size_t i = 0; i < expected_payload.size(); ++i) {
    expected_payload[i] = static_cast<unsigned char>(i ^ 0xa5);
  }
  auto source_keys = std::make_unique<uint64_t[]>(expected_keys.size());
  auto source_payload = std::make_unique<unsigned char[]>(expected_payload.size());
  std::memcpy(source_keys.get(), expected_keys.data(), sizeof(expected_keys));
  std::memcpy(source_payload.get(), expected_payload.data(), expected_payload.size());
  keys.data = source_keys.get();
  payload.data = source_payload.get();
  fa_packet_request_v1 request{};
  Check(fa_observer_packet_default_request(&request, sizeof(request)) == FA_PACKET_OK,
        "actual hook packet defaults failed");
  request.min_payload_bytes = 64;
  Check(fa_observer_start_capture() == FA_OBSERVER_OK,
        "actual hook packet start failed");
  uint64_t capture_id = 0;
  Check(fa_observer_packet_arm(&request, sizeof(request), &capture_id) == FA_PACKET_OK,
        "actual hook packet arm failed");
  throw_original = true;
  bool caught = false;
  try {
    ToyTarget(&receiver_value, &keys, &payload);
  } catch (const Marker &marker) {
    caught = marker.value == 31415;
  }
  throw_original = false;
  Check(caught && original_calls == 4,
        "packet copy changed actual trampoline original exception or count");
  std::memset(source_keys.get(), 0, sizeof(expected_keys));
  std::memset(source_payload.get(), 0, expected_payload.size());
  source_keys.reset();
  source_payload.reset();
  fa_packet_manifest_v1 manifest{};
  std::array<uint64_t, 4> copied_keys{};
  std::array<unsigned char, 123> copied_payload{};
  Check(fa_observer_packet_copy(1, capture_id, copied_keys.data(), sizeof(copied_keys),
                                 copied_payload.data(), copied_payload.size(),
                                 &manifest, sizeof(manifest)) == FA_PACKET_OK &&
            copied_keys == expected_keys && copied_payload == expected_payload &&
            manifest.flags == 7 && manifest.call_sequence == 4 &&
            manifest.copied_keys_bytes == 32 && manifest.copied_payload_bytes == 123,
        "actual hook snapshot retained borrowed pointers or returned incomplete bytes");
  Check(fa_observer_packet_release(1, capture_id) == FA_PACKET_OK,
        "actual hook snapshot release failed");
  fa_observer_stop_capture();
  keys.data = reinterpret_cast<void *>(uintptr_t{1});
  payload.data = reinterpret_cast<void *>(uintptr_t{2});
}

#if defined(__APPLE__) && (defined(__arm64__) || defined(__aarch64__))
extern "C" void fa_fixture_set_callback(void *callback);
extern "C" void fa_fixture_dispatch(void *, const void *, const void *);
struct ReceiverWrapper {
  uint64_t object_header[2];
  void *native_object;
  void *managed_object_id;
};
ReceiverWrapper fixture_receiver{{0, 0}, reinterpret_cast<void *>(uintptr_t{0x1234}),
                                  reinterpret_cast<void *>(uintptr_t{0x5678})};
fa::ObserverCore *fixture_core = nullptr;
uint64_t fixture_calls = 0;
bool fixture_throws = false;

void FixtureCallback(void *native_object, void *managed_object_id,
                      const void *key_data, uint64_t key_count,
                      const void *payload_data, uint64_t payload_count) {
  ++fixture_calls;
  Check(native_object == fixture_receiver.native_object &&
            managed_object_id == fixture_receiver.managed_object_id &&
            key_data == keys.data && key_count == keys.count &&
            payload_data == payload.data && payload_count == payload.count,
        "ADRP/LDR/LDP fixture changed the six-register callback");
  if (fixture_throws) throw Marker{2026};
}

void FixtureReplacement(void *receiver, const void *key_header,
                         const void *payload_header) {
  fixture_core->Forward(receiver, key_header, payload_header);
}

void TestExactDispatchShape(int (*prepare)(void *, void *, void **),
                            int (*commit)(void *)) {
  const std::array<unsigned char, 28> tail = {
      0x08, 0x24, 0x41, 0xa9, 0x2a, 0x0c, 0x40, 0xa9, 0x44, 0x14,
      0x40, 0xa9, 0xe0, 0x03, 0x08, 0xaa, 0xe1, 0x03, 0x09, 0xaa,
      0xe2, 0x03, 0x0a, 0xaa, 0xc0, 0x00, 0x1f, 0xd6};
  Check(std::memcmp(reinterpret_cast<const unsigned char *>(
                        reinterpret_cast<void *>(&fa_fixture_dispatch)) + 8,
                     tail.data(), tail.size()) == 0,
        "fixture does not match the verified dispatch instruction shape");
  fa_fixture_set_callback(reinterpret_cast<void *>(&FixtureCallback));
  static fa::ObserverCore core;
  fixture_core = &core;
  fa_observer_install_report report{};
  Check(core.PrepareAndCommit(reinterpret_cast<void *>(&fa_fixture_dispatch),
                               reinterpret_cast<void *>(&FixtureReplacement),
                               prepare, commit, report) == FA_OBSERVER_OK,
        "ADRP/LDR/LDP hook failed");
  core.StartCapture();
  fa_fixture_dispatch(&fixture_receiver, &keys, &payload);
  Check(fixture_calls == 1, "ADRP/LDR/LDP trampoline did not forward once");
  fixture_throws = true;
  bool caught = false;
  try {
    fa_fixture_dispatch(&fixture_receiver, &keys, &payload);
  } catch (const Marker &marker) {
    caught = marker.value == 2026;
  }
  Check(caught && fixture_calls == 2,
        "ADRP/LDR/LDP trampoline changed native exception unwind");
  fixture_throws = false;
  core.StopCapture();
  fa_fixture_dispatch(&fixture_receiver, &keys, &payload);
  Check(fixture_calls == 3, "ADRP/LDR/LDP stop lost the original callback");
  fa_observer_record records[4]{};
  Check(core.Drain(records, 4) == 2 && records[0].keys_count == 4 &&
            records[0].payload_count == 123,
        "ADRP/LDR/LDP observer record mismatch");
  /* Installed hooks and this static core intentionally remain process-lifetime. */
}
#endif
}  // namespace

int main(int argc, char **argv) {
#if !defined(__APPLE__) || !(defined(__arm64__) || defined(__aarch64__))
  (void)argc;
  (void)argv;
  std::cout << "{\"status\":\"skipped\",\"reason\":\"mac_arm64_only\"}\n";
  return 0;
#else
  if (argc != 3 || std::strcmp(argv[1], "--dobby") != 0) {
    std::cerr << "usage: observer_dobby_toy_test --dobby /absolute/libdobby.dylib\n";
    return 2;
  }
  try {
    std::array<unsigned char, 36> before{};
    std::memcpy(before.data(), reinterpret_cast<void *>(&ToyTarget), before.size());
    fa_observer_install_report production_report{};
    const auto production_result = fa_observer_install(
        reinterpret_cast<void *>(&ToyTarget), argv[2], &production_report,
        sizeof(production_report));
    Check(production_result == FA_OBSERVER_MODULE_HASH_MISMATCH,
          "production installer must reject a non-FM module");
    Check(std::memcmp(before.data(), reinterpret_cast<void *>(&ToyTarget),
                       before.size()) == 0,
          "production rejection changed toy code");

    fa_observer_install_report report{};
    const auto result = fa_observer_test_install_toy(
        reinterpret_cast<void *>(&ToyTarget), argv[2], &report, sizeof(report));
    if (result != FA_OBSERVER_OK) {
      std::cerr << "toy install result=" << fa_observer_result_message(result)
                << " prepare=" << report.prepare_result
                << " commit=" << report.commit_result << '\n';
      return 1;
    }
    Check((report.checks & FA_CHECK_ORIGINAL_PUBLISHED) != 0,
          "real Dobby original not published");
    Check(fa_observer_start_capture() == FA_OBSERVER_OK, "capture start failed");
    ToyTarget(&receiver_value, &keys, &payload);
    Check(original_calls == 1 && argument_errors == 0,
          "real trampoline did not preserve exactly-once arguments");
    throw_original = true;
    bool caught = false;
    try {
      ToyTarget(&receiver_value, &keys, &payload);
    } catch (const Marker &marker) {
      caught = marker.value == 31415;
    }
    Check(caught && original_calls == 2,
          "real trampoline did not preserve original C++ exception");
    throw_original = false;
    fa_observer_stop_capture();
    ToyTarget(&receiver_value, &keys, &payload);
    Check(original_calls == 3 && argument_errors == 0,
          "stop broke the original trampoline");
    std::array<fa_observer_record, 8> records{};
    uint32_t count = 0;
    Check(fa_observer_drain(records.data(), records.size(), sizeof(records[0]),
                             &count) == FA_OBSERVER_OK && count == 2,
          "real observer captured wrong number of records");
    for (uint32_t index = 0; index < count; ++index) {
      Check(records[index].keys_count == 4 && records[index].payload_count == 123,
            "real observer header count differs");
    }

    /* Independently test that this actual Dobby binary leaves a prepared target
     * untouched until Commit and accepts publication before activation.
     */
    void *handle = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
    using Prepare = int (*)(void *, void *, void **);
    using Commit = int (*)(void *);
    auto prepare = reinterpret_cast<Prepare>(dlsym(handle, "DobbyPrepare"));
    auto commit = reinterpret_cast<Commit>(dlsym(handle, "DobbyCommit"));
    Check(prepare != nullptr && commit != nullptr, "staged Dobby API missing");
    void *original = nullptr;
    Check(prepare(reinterpret_cast<void *>(&StagedTarget),
                   reinterpret_cast<void *>(&StagedReplacement), &original) == 0 &&
              original != nullptr,
          "actual Prepare failed");
    StagedTarget(nullptr, nullptr, nullptr);
    Check(staged_original_calls == 1 && staged_replacement_calls == 0,
          "actual Prepare unexpectedly activated target");
    staged_original.store(reinterpret_cast<Forward>(original),
                           std::memory_order_release);
    Check(commit(reinterpret_cast<void *>(&StagedTarget)) == 0,
          "actual Commit failed");
    StagedTarget(nullptr, nullptr, nullptr);
    Check(staged_original_calls == 2 && staged_replacement_calls == 1,
          "actual staged hook forwarding failed");
    TestExactDispatchShape(prepare, commit);
    fa_observer_stats stats{};
    fa_observer_get_stats(&stats, sizeof(stats));
    Check(stats.in_flight_invocations == 0 && stats.invocation_count == 3,
          "real exception leaked in-flight accounting");
    TestOneShotThroughActualHook();
    std::cout << "{\"status\":\"passed\",\"actual_dobby_hooks\":3,"
                 "\"original_calls\":4,\"records\":2,"
                 "\"exception_preserved\":true,\"adrp_ldp_fixture\":true,"
                 "\"one_shot_complete_after_source_free\":true,"
                 "\"game_process_touched\":false}\n";
    return 0;
  } catch (const std::exception &exception) {
    std::cerr << "toy hook test failed: " << exception.what() << '\n';
    return 1;
  }
#endif
}
