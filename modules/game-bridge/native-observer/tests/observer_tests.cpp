#include "fa_native_observer.h"
#include "observer_core.hpp"

#include <array>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <unordered_set>
#include <vector>

namespace {

struct SpanHeader {
  const void *data;
  uint64_t count;
};
static_assert(sizeof(SpanHeader) == 16);
static_assert(offsetof(SpanHeader, count) == 8);

void Check(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}

fa::ObserverCore *active_core = nullptr;
void *expected_receiver = nullptr;
const void *expected_keys = nullptr;
const void *expected_payload = nullptr;
std::atomic<uint64_t> original_calls{0};
std::atomic<uint64_t> argument_errors{0};
bool original_throws = false;
bool prepare_fails = false;
bool prepare_returns_null = false;
bool prepare_returns_target = false;
bool prepare_returns_replacement = false;
bool prepare_throws = false;
bool commit_fails = false;
bool commit_throws = false;
bool commit_enters_replacement = false;
int prepare_calls = 0;
int commit_calls = 0;

struct OriginalException { int marker; };

void Original(void *receiver, const void *keys, const void *payload) {
  original_calls.fetch_add(1, std::memory_order_relaxed);
  if (receiver != expected_receiver || keys != expected_keys ||
      payload != expected_payload) {
    argument_errors.fetch_add(1, std::memory_order_relaxed);
  }
  if (original_throws) throw OriginalException{2718};
}

void Replacement(void *receiver, const void *keys, const void *payload) {
  active_core->Forward(receiver, keys, payload);
}

int Prepare(void *target, void *replacement, void **original) {
  ++prepare_calls;
  Check(active_core->InstallState() == FA_OBSERVER_INSTALLING,
        "prepare must run before prepared state");
  Check(active_core->OriginalAddress() == 0,
        "original must not have been guessed before prepare");
  if (prepare_throws) throw std::runtime_error("test prepare exception");
  if (prepare_fails) return -77;
  if (prepare_returns_null) {
    *original = nullptr;
  } else if (prepare_returns_target) {
    *original = target;
  } else if (prepare_returns_replacement) {
    *original = replacement;
  } else {
    *original = reinterpret_cast<void *>(&Original);
  }
  return 0;
}

int Commit(void *) {
  ++commit_calls;
  Check(active_core->InstallState() == FA_OBSERVER_PREPARED,
        "commit requires prepared state");
  Check(active_core->OriginalAddress() == reinterpret_cast<uintptr_t>(&Original),
        "original must be published before commit can activate replacement");
  if (commit_throws) throw std::runtime_error("test commit exception");
  if (commit_enters_replacement) {
    Replacement(expected_receiver, expected_keys, expected_payload);
  }
  return commit_fails ? -88 : 0;
}

void Reset(fa::ObserverCore &core, void *receiver, const void *keys,
            const void *payload) {
  active_core = &core;
  expected_receiver = receiver;
  expected_keys = keys;
  expected_payload = payload;
  original_calls = 0;
  argument_errors = 0;
  original_throws = false;
  prepare_fails = false;
  prepare_returns_null = false;
  prepare_returns_target = false;
  prepare_returns_replacement = false;
  prepare_throws = false;
  commit_fails = false;
  commit_throws = false;
  commit_enters_replacement = false;
  prepare_calls = 0;
  commit_calls = 0;
}

int Install(fa::ObserverCore &core, fa_observer_install_report &report) {
  return core.PrepareAndCommit(reinterpret_cast<void *>(uintptr_t{0x1234}),
                               reinterpret_cast<void *>(&Replacement), &Prepare,
                               &Commit, report);
}

fa_observer_stats Stats(const fa::ObserverCore &core) {
  fa_observer_stats stats{};
  core.GetStats(stats);
  return stats;
}

void TestPublishOrderAndForwarding() {
  fa::ObserverCore core;
  SpanHeader keys{reinterpret_cast<void *>(uintptr_t{1}), 3};
  SpanHeader payload{reinterpret_cast<void *>(uintptr_t{2}), 71};
  int receiver = 5;
  Reset(core, &receiver, &keys, &payload);
  Check(core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
        "uninstalled observer cannot capture");
  commit_enters_replacement = true;
  fa_observer_install_report report{};
  Check(Install(core, report) == FA_OBSERVER_OK, "install failed");
  Check(original_calls == 1 && argument_errors == 0,
        "commit-time entry must forward exact arguments once");
  Check((report.checks & FA_CHECK_ORIGINAL_PUBLISHED) != 0,
        "publication check missing");
  Check(Stats(core).enqueued_count == 0,
        "installation must leave capture disabled");
  Check(core.StartCapture() == FA_OBSERVER_OK, "start failed");
  core.Forward(&receiver, &keys, &payload);
  Check(original_calls == 2 && argument_errors == 0,
        "forward must call original exactly once");
  fa_observer_record record{};
  Check(core.Drain(&record, 1) == 1, "record missing");
  Check(record.call_sequence == 2 && record.keys_count == 3 &&
            record.payload_count == 71,
        "captured header counts differ");
  Check((record.flags & FA_RECORD_KEYS_COUNT_KNOWN) != 0 &&
            (record.flags & FA_RECORD_PAYLOAD_COUNT_KNOWN) != 0,
        "known header flags missing");
  Check(record.monotonic_ns != 0 && record.native_thread_id != 0,
        "clock/thread diagnostics missing");
  core.StopCapture();
  core.Forward(&receiver, &keys, &payload);
  Check(original_calls == 3 && core.Drain(&record, 1) == 0,
        "stop must stop copying and keep forwarding");
  Check(Install(core, report) == FA_OBSERVER_ALREADY_INSTALLED,
        "second installation must be refused");
}

void TestNullZeroAndOverflowCounts() {
  fa::ObserverCore core;
  int receiver = 0;
  Reset(core, &receiver, nullptr, nullptr);
  fa_observer_install_report report{};
  Check(Install(core, report) == FA_OBSERVER_OK, "install failed");
  core.StartCapture();
  core.Forward(&receiver, nullptr, nullptr);
  fa_observer_record record{};
  Check(core.Drain(&record, 1) == 1 && record.flags == 0 &&
            record.keys_count == 0 && record.payload_count == 0,
        "null headers must remain unknown, not known empty");

  SpanHeader zero{reinterpret_cast<void *>(uintptr_t{1}), 0};
  expected_keys = &zero;
  expected_payload = &zero;
  core.Forward(&receiver, &zero, &zero);
  Check(core.Drain(&record, 1) == 1 && record.keys_count == 0 &&
            (record.flags & FA_RECORD_KEYS_COUNT_KNOWN) != 0 &&
            (record.flags & FA_RECORD_PAYLOAD_COUNT_KNOWN) != 0,
        "known zero must remain distinct from unknown");

  SpanHeader excessive{reinterpret_cast<void *>(uintptr_t{1}), UINT64_MAX};
  expected_keys = &excessive;
  expected_payload = &excessive;
  core.Forward(&receiver, &excessive, &excessive);
  Check(core.Drain(&record, 1) == 1 && record.keys_count == UINT64_MAX &&
            (record.flags & FA_RECORD_KEYS_BYTE_SIZE_OVERFLOW) != 0 &&
            (record.flags & FA_RECORD_KEYS_COUNT_EXCEEDS_INT32) != 0 &&
            (record.flags & FA_RECORD_PAYLOAD_COUNT_EXCEEDS_INT32) != 0,
        "oversize count flags missing");
  Check(argument_errors == 0 && original_calls == 3,
        "null/oversize arguments were changed or original skipped");
}

void TestOriginalExceptionKeepsNativeUnwind() {
  fa::ObserverCore core;
  SpanHeader header{nullptr, 0};
  int receiver = 1;
  Reset(core, &receiver, &header, &header);
  fa_observer_install_report report{};
  Check(Install(core, report) == FA_OBSERVER_OK, "install failed");
  core.StartCapture();
  original_throws = true;
  bool caught = false;
  try {
    core.Forward(&receiver, &header, &header);
  } catch (const OriginalException &exception) {
    caught = exception.marker == 2718;
  }
  Check(caught && original_calls == 1 && argument_errors == 0,
        "original exception was swallowed, changed, or forwarded twice");
  Check(Stats(core).in_flight_invocations == 0,
        "native exception leaked in-flight accounting");
}

void TestInstallationFailuresDoNotCommitUnpublishedOriginal() {
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    fa_observer_install_report report{};
    void *replacement = reinterpret_cast<void *>(&Replacement);
    Check(core.PrepareAndCommit(replacement, replacement, &Prepare, &Commit,
                                 report) == FA_OBSERVER_INVALID_ARGUMENT &&
              prepare_calls == 0 && commit_calls == 0 &&
              core.OriginalAddress() == 0 &&
              core.InstallState() == FA_OBSERVER_UNINSTALLED,
          "observer cannot replace its own entry");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    prepare_fails = true;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_PREPARE_FAILED &&
              commit_calls == 0 && core.OriginalAddress() == 0,
          "prepare failure must not commit");
    Check(core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
          "failed prepare must not start");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    prepare_returns_null = true;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_INVALID_ORIGINAL &&
              commit_calls == 0,
          "null original must not commit");
  }
  for (unsigned invalid_alias = 0; invalid_alias < 2; ++invalid_alias) {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    prepare_returns_target = invalid_alias == 0;
    prepare_returns_replacement = invalid_alias == 1;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_INVALID_ORIGINAL &&
              prepare_calls == 1 && commit_calls == 0 &&
              core.OriginalAddress() == 0 &&
              (report.checks & FA_CHECK_ORIGINAL_PUBLISHED) == 0 &&
              core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
          "target/self alias must be rejected before publication or commit");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    commit_fails = true;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_COMMIT_FAILED &&
              core.OriginalAddress() != 0,
          "failed commit must retain original");
    core.Forward(nullptr, nullptr, nullptr);
    Check(original_calls == 1 &&
              core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
          "partial commit must stay forwarding-capable and capture-disabled");
    Check(Install(core, report) == FA_OBSERVER_INSTALL_NOT_RETRYABLE,
          "failed native install must not be guessed-retried");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_OK, "install failed");
    core.RejectUnverifiedPatch();
    Check(core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
          "unverified code patch must not become capture-ready");
    core.Forward(nullptr, nullptr, nullptr);
    Check(original_calls == 1,
          "unverified patch must retain original for a partial native install");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    prepare_throws = true;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_CONTROL_EXCEPTION &&
              core.OriginalAddress() == 0 && commit_calls == 0,
          "prepare exception escaped control boundary");
  }
  {
    fa::ObserverCore core;
    Reset(core, nullptr, nullptr, nullptr);
    commit_throws = true;
    fa_observer_install_report report{};
    Check(Install(core, report) == FA_OBSERVER_CONTROL_EXCEPTION &&
              core.OriginalAddress() != 0,
          "commit exception escaped control boundary or lost original");
    core.Forward(nullptr, nullptr, nullptr);
    Check(original_calls == 1 &&
              core.StartCapture() == FA_OBSERVER_NOT_INSTALLED,
          "commit exception broke safe forwarding");
  }
}

void TestConcurrentBoundedQueue() {
  fa::ObserverCore core;
  SpanHeader keys{reinterpret_cast<void *>(uintptr_t{1}), 12};
  SpanHeader payload{reinterpret_cast<void *>(uintptr_t{2}), 64};
  int receiver = 8;
  Reset(core, &receiver, &keys, &payload);
  fa_observer_install_report report{};
  Check(Install(core, report) == FA_OBSERVER_OK, "install failed");
  core.StartCapture();
  constexpr unsigned threads = 6;
  constexpr unsigned per_thread = 20000;
  std::atomic<unsigned> ready{0};
  std::atomic<bool> start{false};
  std::vector<std::thread> producers;
  for (unsigned index = 0; index < threads; ++index) {
    producers.emplace_back([&] {
      ready.fetch_add(1, std::memory_order_release);
      while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
      for (unsigned iteration = 0; iteration < per_thread; ++iteration) {
        core.Forward(&receiver, &keys, &payload);
      }
    });
  }
  while (ready.load(std::memory_order_acquire) != threads) std::this_thread::yield();
  start.store(true, std::memory_order_release);
  for (auto &producer : producers) producer.join();
  const auto before = Stats(core);
  constexpr uint64_t total = threads * per_thread;
  Check(original_calls == total && argument_errors == 0,
        "concurrent forwards lost, repeated, or changed arguments");
  Check(before.invocation_count == total && before.in_flight_invocations == 0,
        "concurrent accounting mismatch");
  Check(before.enqueued_count + before.overflow_dropped +
                before.contention_dropped == total &&
            before.enqueued_count <= FA_OBSERVER_QUEUE_CAPACITY &&
            before.overflow_dropped != 0,
        "bounded drops must be explicit and account for every capture");
  std::array<fa_observer_record, FA_OBSERVER_QUEUE_CAPACITY> records{};
  const auto count = core.Drain(records.data(), records.size());
  Check(count == before.enqueued_count, "drain count differs from queue");
  std::unordered_set<uint64_t> sequences;
  for (uint32_t index = 0; index < count; ++index) {
    Check(records[index].keys_count == 12 && records[index].payload_count == 64 &&
              records[index].call_sequence >= 1 &&
              records[index].call_sequence <= total,
          "concurrent record corruption");
    Check(sequences.insert(records[index].call_sequence).second,
          "duplicate concurrent record");
  }
  Check(Stats(core).queue_approx_size == 0 &&
            Stats(core).drained_count == count,
        "queue did not become empty");
}

void TestCAbiBounds() {
  Check(fa_observer_abi_version() == 1, "ABI version mismatch");
  const auto first_clock = fa_observer_monotonic_ns();
  Check(first_clock != 0 && fa_observer_monotonic_ns() >= first_clock,
        "native monotonic clock sample failed");
  fa_observer_stats stats{};
  Check(fa_observer_get_stats(&stats, sizeof(stats)) == FA_OBSERVER_OK &&
            stats.struct_size == sizeof(stats),
        "stats layout mismatch");
  Check(fa_observer_get_stats(&stats, sizeof(stats) - 1) ==
            FA_OBSERVER_BUFFER_TOO_SMALL,
        "small stats buffer accepted");
  Check(fa_observer_start_capture() == FA_OBSERVER_NOT_INSTALLED,
        "public capture started before installation");
  uint32_t count = 99;
  Check(fa_observer_drain(nullptr, 0, sizeof(fa_observer_record), &count) ==
                FA_OBSERVER_OK && count == 0,
        "zero capacity drain failed");
  Check(fa_observer_drain(nullptr, 1, sizeof(fa_observer_record), &count) ==
            FA_OBSERVER_INVALID_ARGUMENT,
        "null output buffer accepted");
  fa_observer_record record{};
  Check(fa_observer_drain(&record, 1, 1, &count) == FA_OBSERVER_INVALID_ARGUMENT,
        "wrong record layout accepted");
  Check(fa_observer_drain(&record, 4097, sizeof(record), &count) ==
            FA_OBSERVER_INVALID_ARGUMENT,
        "unbounded drain accepted");
  fa_observer_install_report report{};
  Check(fa_observer_install(nullptr, "unused", &report, sizeof(report)) ==
            FA_OBSERVER_INVALID_ARGUMENT,
        "null anchor accepted");
}

}  // namespace

int main() {
  try {
    TestPublishOrderAndForwarding();
    TestNullZeroAndOverflowCounts();
    TestOriginalExceptionKeepsNativeUnwind();
    TestInstallationFailuresDoNotCommitUnpublishedOriginal();
    TestConcurrentBoundedQueue();
    TestCAbiBounds();
    std::cout << "{\"status\":\"passed\",\"tests\":6,"
                 "\"concurrent_original_calls\":120000,"
                 "\"game_process_touched\":false}\n";
    return 0;
  } catch (const std::exception &exception) {
    std::cerr << "observer test failed: " << exception.what() << '\n';
    return 1;
  }
}
