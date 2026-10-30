#include "fa_native_observer.h"
#include "observer_core.hpp"

#include <array>
#include <climits>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <new>
#include <string>

#if defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <mach/vm_prot.h>
#endif

namespace {

constexpr char kGamePluginSha[] =
    "2e915b0f264920ae1205b111f45d50e354ac0e7d0b6e136b99189c24b265f431";
constexpr char kDobbySha[] =
    "0cab79106f5b309409fd752ea5fe85e74c4b0c04b35d6508d5c2556bc297bac6";
constexpr char kDobbyBuild[] = "Dobby-20260703-9d27180";
constexpr char kAnchorExport[] =
    "game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr";
constexpr uintptr_t kAnchorRva = 0x16c18;
constexpr uintptr_t kDispatchDelta = 0xC;
constexpr uintptr_t kCallbackSlotRva = 0x56d10e8;
constexpr std::array<unsigned char, 36> kOriginalBytes = {
    0xc8, 0xb5, 0x02, 0xf0, 0x06, 0x75, 0x40, 0xf9, 0x08,
    0x24, 0x41, 0xa9, 0x2a, 0x0c, 0x40, 0xa9, 0x44, 0x14,
    0x40, 0xa9, 0xe0, 0x03, 0x08, 0xaa, 0xe1, 0x03, 0x09,
    0xaa, 0xe2, 0x03, 0x0a, 0xaa, 0xc0, 0x00, 0x1f, 0xd6};

/* A committed native callback outlives managed stop. Construct in static image
 * storage without registering a C++ destructor; the pinned image owns it until
 * process termination, including its control-plane mutex and packet buffers.
 */
alignas(fa::ObserverCore) unsigned char g_observer_storage[sizeof(fa::ObserverCore)];
fa::ObserverCore &g_observer =
    *::new (static_cast<void *>(g_observer_storage)) fa::ObserverCore();
std::mutex g_install_mutex;
void *g_dobby_handle = nullptr;
void *g_self_handle = nullptr;
void *g_target = nullptr;
uint32_t g_install_checks = 0;
int32_t g_prepare_result = INT32_MIN;
int32_t g_commit_result = INT32_MIN;

#if defined(_MSC_VER)
__declspec(noinline)
#else
__attribute__((noinline))
#endif
void ObserverDispatch(void *receiver, const void *keys, const void *payload) {
  g_observer.Forward(receiver, keys, payload);
}

void InitializeReport(fa_observer_install_report &report) noexcept {
  report = {};
  report.abi_version = FA_OBSERVER_ABI_VERSION;
  report.struct_size = sizeof(report);
  report.prepare_result = g_prepare_result;
  report.commit_result = g_commit_result;
  report.target_address = reinterpret_cast<uintptr_t>(g_target);
  report.original_address = g_observer.OriginalAddress();
  report.install_state = g_observer.InstallState();
  report.checks = g_install_checks;
}

int FinishReport(int result, fa_observer_install_report &report) noexcept {
  report.result = result;
  report.install_state = g_observer.InstallState();
  report.original_address = g_observer.OriginalAddress();
  g_install_checks = report.checks;
  g_prepare_result = report.prepare_result;
  g_commit_result = report.commit_result;
  return result;
}

#if defined(__APPLE__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
/* This system SHA implementation is used only on the installation control
 * path. Nothing hashes, allocates, opens files or loads a library in Dispatch.
 */
bool FileShaMatches(const char *path, const char *expected) {
  FILE *file = std::fopen(path, "rb");
  if (file == nullptr) return false;
  CC_SHA256_CTX context{};
  CC_SHA256_Init(&context);
  std::array<unsigned char, 64 * 1024> buffer{};
  bool ok = true;
  for (;;) {
    const auto size = std::fread(buffer.data(), 1, buffer.size(), file);
    if (size != 0) {
      CC_SHA256_Update(&context, buffer.data(), static_cast<CC_LONG>(size));
    }
    if (size < buffer.size()) {
      ok = std::ferror(file) == 0;
      break;
    }
  }
  std::fclose(file);
  unsigned char digest[CC_SHA256_DIGEST_LENGTH]{};
  CC_SHA256_Final(digest, &context);
  char text[CC_SHA256_DIGEST_LENGTH * 2 + 1]{};
  constexpr char hex[] = "0123456789abcdef";
  for (size_t index = 0; index < sizeof(digest); ++index) {
    text[index * 2] = hex[digest[index] >> 4];
    text[index * 2 + 1] = hex[digest[index] & 15];
  }
  return ok && std::strcmp(text, expected) == 0;
}
#pragma clang diagnostic pop

bool ModuleRangeReadable(const void *base_pointer, uintptr_t start,
                         size_t length) noexcept {
  const auto *header = static_cast<const mach_header_64 *>(base_pointer);
  if (header == nullptr || header->magic != MH_MAGIC_64 ||
      header->ncmds > 4096 || header->sizeofcmds > 16 * 1024 * 1024 ||
      start > UINTPTR_MAX - length) {
    return false;
  }
  const auto *commands = reinterpret_cast<const unsigned char *>(header + 1);
  const auto *limit = commands + header->sizeofcmds;
  uint64_t preferred_base = UINT64_MAX;
  const auto *cursor = commands;
  for (uint32_t index = 0; index < header->ncmds; ++index) {
    if (static_cast<size_t>(limit - cursor) < sizeof(load_command)) return false;
    const auto *command = reinterpret_cast<const load_command *>(cursor);
    if (command->cmdsize < sizeof(load_command) ||
        command->cmdsize > static_cast<size_t>(limit - cursor)) return false;
    if (command->cmd == LC_SEGMENT_64 &&
        command->cmdsize >= sizeof(segment_command_64)) {
      const auto *segment = reinterpret_cast<const segment_command_64 *>(cursor);
      if (segment->fileoff == 0 && segment->filesize != 0) {
        preferred_base = segment->vmaddr;
        break;
      }
    }
    cursor += command->cmdsize;
  }
  if (preferred_base == UINT64_MAX) return false;
  const auto slide = reinterpret_cast<uintptr_t>(header) - preferred_base;
  cursor = commands;
  for (uint32_t index = 0; index < header->ncmds; ++index) {
    if (static_cast<size_t>(limit - cursor) < sizeof(load_command)) return false;
    const auto *command = reinterpret_cast<const load_command *>(cursor);
    if (command->cmdsize < sizeof(load_command) ||
        command->cmdsize > static_cast<size_t>(limit - cursor)) return false;
    if (command->cmd == LC_SEGMENT_64 &&
        command->cmdsize >= sizeof(segment_command_64)) {
      const auto *segment = reinterpret_cast<const segment_command_64 *>(cursor);
      if ((segment->initprot & VM_PROT_READ) != 0 &&
          segment->vmaddr <= UINTPTR_MAX - slide) {
        const auto lower = segment->vmaddr + slide;
        if (segment->vmsize <= UINTPTR_MAX - lower && start >= lower &&
            start + length <= lower + segment->vmsize) {
          return true;
        }
      }
    }
    cursor += command->cmdsize;
  }
  return false;
}

bool PinSelf() {
  if (g_self_handle != nullptr) return true;
  Dl_info info{};
  if (dladdr(reinterpret_cast<void *>(&fa_observer_install), &info) == 0 ||
      info.dli_fname == nullptr) return false;
  /* Retained until process exit. Do not provide a dlclose/uninstall endpoint. */
  g_self_handle = dlopen(info.dli_fname, RTLD_NOW | RTLD_LOCAL);
  return g_self_handle != nullptr;
}

int LoadDobby(const char *path, fa::PrepareFunction &prepare,
              fa::CommitFunction &commit,
              fa_observer_install_report &report) {
  if (!FileShaMatches(path, kDobbySha)) return FA_OBSERVER_DOBBY_HASH_MISMATCH;
  report.checks |= FA_CHECK_DOBBY_HASH;
  if (g_dobby_handle == nullptr) {
    g_dobby_handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
  }
  if (g_dobby_handle == nullptr) return FA_OBSERVER_DOBBY_LOAD_FAILED;
  using VersionFunction = const char *(*)();
  const auto version = reinterpret_cast<VersionFunction>(
      dlsym(g_dobby_handle, "DobbyBuildVersion"));
  prepare = reinterpret_cast<fa::PrepareFunction>(
      dlsym(g_dobby_handle, "DobbyPrepare"));
  commit = reinterpret_cast<fa::CommitFunction>(
      dlsym(g_dobby_handle, "DobbyCommit"));
  if (version == nullptr || prepare == nullptr || commit == nullptr) {
    return FA_OBSERVER_DOBBY_ABI_MISMATCH;
  }
  const char *build = version();
  if (build == nullptr || std::strstr(build, kDobbyBuild) == nullptr) {
    return FA_OBSERVER_DOBBY_ABI_MISMATCH;
  }
  report.checks |= FA_CHECK_DOBBY_VERSION;
  return FA_OBSERVER_OK;
}

int VerifyGameTarget(void *anchor, void *&target,
                     fa_observer_install_report &report) {
  Dl_info info{};
  if (dladdr(anchor, &info) == 0 || info.dli_fname == nullptr ||
      info.dli_fbase == nullptr) return FA_OBSERVER_MODULE_NOT_FOUND;
  if (!FileShaMatches(info.dli_fname, kGamePluginSha)) {
    return FA_OBSERVER_MODULE_HASH_MISMATCH;
  }
  report.checks |= FA_CHECK_MODULE_HASH;
  const auto base = reinterpret_cast<uintptr_t>(info.dli_fbase);
  if (reinterpret_cast<uintptr_t>(anchor) < base ||
      reinterpret_cast<uintptr_t>(anchor) - base != kAnchorRva) {
    return FA_OBSERVER_ANCHOR_MISMATCH;
  }
  /* NOLOAD prevents running another module's constructors. This reference is
   * also deliberately retained for the lifetime of the installed trampoline.
   */
  void *module = dlopen(info.dli_fname, RTLD_LAZY | RTLD_LOCAL | RTLD_NOLOAD);
  if (module == nullptr || dlsym(module, kAnchorExport) != anchor) {
    return FA_OBSERVER_ANCHOR_MISMATCH;
  }
  report.checks |= FA_CHECK_ANCHOR;
  target = reinterpret_cast<void *>(reinterpret_cast<uintptr_t>(anchor) +
                                    kDispatchDelta);
  report.target_address = reinterpret_cast<uintptr_t>(target);
  if (!ModuleRangeReadable(info.dli_fbase,
                           reinterpret_cast<uintptr_t>(target),
                           kOriginalBytes.size()) ||
      std::memcmp(target, kOriginalBytes.data(), kOriginalBytes.size()) != 0) {
    return FA_OBSERVER_TARGET_BYTES_MISMATCH;
  }
  report.checks |= FA_CHECK_TARGET_BYTES;
  if (base > UINTPTR_MAX - kCallbackSlotRva) {
    return FA_OBSERVER_CALLBACK_NOT_READY;
  }
  const auto callback_slot = base + kCallbackSlotRva;
  if (!ModuleRangeReadable(info.dli_fbase, callback_slot, sizeof(void *))) {
    return FA_OBSERVER_CALLBACK_NOT_READY;
  }
  void *callback = nullptr;
  std::memcpy(&callback, reinterpret_cast<const void *>(callback_slot),
              sizeof(callback));
  if (callback == nullptr) return FA_OBSERVER_CALLBACK_NOT_READY;
  report.checks |= FA_CHECK_CALLBACK_READY;
  return FA_OBSERVER_OK;
}
#endif

int InstallValidated(void *target, const char *dobby_path,
                     fa_observer_install_report &report, bool pin_self) {
#if defined(__APPLE__) && (defined(__arm64__) || defined(__aarch64__))
  fa::PrepareFunction prepare = nullptr;
  fa::CommitFunction commit = nullptr;
  const auto load_result = LoadDobby(dobby_path, prepare, commit, report);
  if (load_result != FA_OBSERVER_OK) return load_result;
  if (pin_self) {
    if (!PinSelf()) return FA_OBSERVER_SELF_PIN_FAILED;
    report.checks |= FA_CHECK_SELF_PINNED;
  }
  g_target = target;
  report.target_address = reinterpret_cast<uintptr_t>(target);
  const auto result = g_observer.PrepareAndCommit(
      target, reinterpret_cast<void *>(&ObserverDispatch), prepare, commit,
      report);
  return result;
#else
  (void)target;
  (void)dobby_path;
  (void)report;
  (void)pin_self;
  return FA_OBSERVER_UNSUPPORTED_PLATFORM;
#endif
}

}  // namespace

extern "C" {

uint32_t fa_observer_abi_version(void) { return FA_OBSERVER_ABI_VERSION; }

uint64_t fa_observer_monotonic_ns(void) {
  return fa::MonotonicNanosecondsForControl();
}

int fa_observer_install(void *anchor, const char *dobby_path,
                        fa_observer_install_report *report,
                        uint32_t report_size) {
  if (report == nullptr || report_size < sizeof(*report)) {
    return report == nullptr ? FA_OBSERVER_INVALID_ARGUMENT
                             : FA_OBSERVER_BUFFER_TOO_SMALL;
  }
  try {
    std::lock_guard<std::mutex> lock(g_install_mutex);
    InitializeReport(*report);
    if (anchor == nullptr || dobby_path == nullptr || dobby_path[0] == '\0') {
      return FinishReport(FA_OBSERVER_INVALID_ARGUMENT, *report);
    }
    if (g_observer.InstallState() != FA_OBSERVER_UNINSTALLED) {
      return FinishReport(g_observer.InstallState() == FA_OBSERVER_COMMITTED
                              ? FA_OBSERVER_ALREADY_INSTALLED
                              : FA_OBSERVER_INSTALL_NOT_RETRYABLE,
                           *report);
    }
#if defined(__APPLE__) && (defined(__arm64__) || defined(__aarch64__))
    void *target = nullptr;
    const auto validation = VerifyGameTarget(anchor, target, *report);
    if (validation != FA_OBSERVER_OK) return FinishReport(validation, *report);
    const auto result = InstallValidated(target, dobby_path, *report, true);
    if (result == FA_OBSERVER_OK) {
      if (std::memcmp(target, kOriginalBytes.data(), kOriginalBytes.size()) == 0) {
        /* The native library may have claimed success without a code patch.
         * Keep its original/trampoline pinned and disabled; never guess retry.
         */
        g_observer.RejectUnverifiedPatch();
        return FinishReport(FA_OBSERVER_PATCH_NOT_OBSERVED, *report);
      }
      report->checks |= FA_CHECK_PATCH_CHANGED_BYTES;
    }
    return FinishReport(result, *report);
#else
    return FinishReport(FA_OBSERVER_UNSUPPORTED_PLATFORM, *report);
#endif
  } catch (...) {
    g_observer.StopCapture();
    report->result = FA_OBSERVER_CONTROL_EXCEPTION;
    report->install_state = g_observer.InstallState();
    return FA_OBSERVER_CONTROL_EXCEPTION;
  }
}

int fa_observer_start_capture(void) { return g_observer.StartCapture(); }

int fa_observer_stop_capture(void) {
  g_observer.StopCapture();
  return FA_OBSERVER_OK;
}

int fa_observer_drain(fa_observer_record *records, uint32_t capacity,
                      uint32_t record_size, uint32_t *out_count) {
  if (out_count == nullptr) return FA_OBSERVER_INVALID_ARGUMENT;
  *out_count = 0;
  if (record_size != sizeof(fa_observer_record) || capacity > 4096 ||
      (capacity != 0 && records == nullptr)) return FA_OBSERVER_INVALID_ARGUMENT;
  *out_count = g_observer.Drain(records, capacity);
  return FA_OBSERVER_OK;
}

int fa_observer_get_stats(fa_observer_stats *stats, uint32_t stats_size) {
  if (stats == nullptr) return FA_OBSERVER_INVALID_ARGUMENT;
  if (stats_size < sizeof(*stats)) return FA_OBSERVER_BUFFER_TOO_SMALL;
  g_observer.GetStats(*stats);
  return FA_OBSERVER_OK;
}

const char *fa_observer_result_message(int result) {
  switch (result) {
    case FA_OBSERVER_OK: return "ok";
    case FA_OBSERVER_INVALID_ARGUMENT: return "invalid_argument";
    case FA_OBSERVER_BUFFER_TOO_SMALL: return "buffer_too_small";
    case FA_OBSERVER_UNSUPPORTED_PLATFORM: return "unsupported_platform";
    case FA_OBSERVER_MODULE_NOT_FOUND: return "module_not_found";
    case FA_OBSERVER_MODULE_HASH_MISMATCH: return "module_hash_mismatch";
    case FA_OBSERVER_ANCHOR_MISMATCH: return "anchor_mismatch";
    case FA_OBSERVER_TARGET_BYTES_MISMATCH: return "target_bytes_mismatch";
    case FA_OBSERVER_CALLBACK_NOT_READY: return "callback_not_ready";
    case FA_OBSERVER_DOBBY_HASH_MISMATCH: return "dobby_hash_mismatch";
    case FA_OBSERVER_DOBBY_LOAD_FAILED: return "dobby_load_failed";
    case FA_OBSERVER_DOBBY_ABI_MISMATCH: return "dobby_abi_mismatch";
    case FA_OBSERVER_SELF_PIN_FAILED: return "self_pin_failed";
    case FA_OBSERVER_ALREADY_INSTALLED: return "already_installed";
    case FA_OBSERVER_INSTALL_NOT_RETRYABLE: return "install_not_retryable";
    case FA_OBSERVER_PREPARE_FAILED: return "prepare_failed";
    case FA_OBSERVER_INVALID_ORIGINAL: return "invalid_original";
    case FA_OBSERVER_COMMIT_FAILED: return "commit_failed";
    case FA_OBSERVER_CONTROL_EXCEPTION: return "control_exception";
    case FA_OBSERVER_NOT_INSTALLED: return "not_installed";
    case FA_OBSERVER_PATCH_NOT_OBSERVED: return "patch_not_observed";
    default: return "unknown_result";
  }
}

uint32_t fa_observer_packet_abi_version(void) { return FA_PACKET_ABI_VERSION; }

int fa_observer_packet_default_request(fa_packet_request_v1 *request,
                                        uint32_t request_size) {
  return fa::PacketCapture::DefaultRequest(request, request_size);
}

int fa_observer_packet_arm(const fa_packet_request_v1 *request,
                            uint32_t request_size, uint64_t *out_capture_id) {
  return g_observer.ArmPacket(request, request_size, out_capture_id);
}

int fa_observer_packet_get_manifest(uint32_t version, uint64_t capture_id,
                                     fa_packet_manifest_v1 *manifest,
                                     uint32_t manifest_size) {
  return g_observer.GetPacketManifest(version, capture_id, manifest, manifest_size);
}

int fa_observer_packet_copy(uint32_t version, uint64_t capture_id,
                             void *keys_buffer, uint64_t keys_capacity,
                             void *payload_buffer, uint64_t payload_capacity,
                             fa_packet_manifest_v1 *manifest,
                             uint32_t manifest_size) {
  return g_observer.CopyPacket(version, capture_id, keys_buffer, keys_capacity,
                               payload_buffer, payload_capacity, manifest,
                               manifest_size);
}

int fa_observer_packet_cancel(uint32_t version, uint64_t capture_id) {
  return g_observer.CancelPacket(version, capture_id);
}

int fa_observer_packet_release(uint32_t version, uint64_t capture_id) {
  return g_observer.ReleasePacket(version, capture_id);
}

const char *fa_observer_packet_result_message(int result) {
  switch (result) {
    case FA_PACKET_OK: return "ok";
    case FA_PACKET_INVALID_ARGUMENT: return "invalid_argument";
    case FA_PACKET_UNSUPPORTED_VERSION: return "unsupported_version";
    case FA_PACKET_BUFFER_TOO_SMALL: return "buffer_too_small";
    case FA_PACKET_NOT_INSTALLED: return "not_installed";
    case FA_PACKET_LEGACY_CAPTURE_DISABLED: return "legacy_capture_disabled";
    case FA_PACKET_BUSY: return "busy";
    case FA_PACKET_WRONG_CAPTURE_ID: return "wrong_capture_id";
    case FA_PACKET_NOT_READY: return "not_ready";
    case FA_PACKET_CANCEL_PENDING: return "cancel_pending";
    case FA_PACKET_CANCELLED_RESULT: return "cancelled";
    case FA_PACKET_NEEDS_RELEASE: return "needs_release";
    case FA_PACKET_ALREADY_READY: return "already_ready";
    case FA_PACKET_NO_CAPTURE: return "no_capture";
    case FA_PACKET_ID_EXHAUSTED: return "id_exhausted";
    case FA_PACKET_CONTROL_EXCEPTION: return "control_exception";
    default: return "unknown_result";
  }
}

#ifdef FA_OBSERVER_TESTING
int fa_observer_test_install_toy(void *target, const char *dobby_path,
                                 fa_observer_install_report *report,
                                 uint32_t report_size) {
  if (report == nullptr || report_size < sizeof(*report) || target == nullptr ||
      dobby_path == nullptr) return FA_OBSERVER_INVALID_ARGUMENT;
  try {
    std::lock_guard<std::mutex> lock(g_install_mutex);
    InitializeReport(*report);
    /* The test code resides in this process's executable and cannot unload. */
    return FinishReport(InstallValidated(target, dobby_path, *report, false),
                         *report);
  } catch (...) {
    g_observer.StopCapture();
    return FinishReport(FA_OBSERVER_CONTROL_EXCEPTION, *report);
  }
}
#endif

}  // extern "C"
