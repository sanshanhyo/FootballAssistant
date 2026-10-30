#ifndef FA_NATIVE_OBSERVER_H
#define FA_NATIVE_OBSERVER_H

#include <stdint.h>

#if defined(_WIN32)
#define FA_OBSERVER_API __declspec(dllexport)
#else
#define FA_OBSERVER_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum { FA_OBSERVER_ABI_VERSION = 1, FA_OBSERVER_QUEUE_CAPACITY = 256 };

typedef enum fa_observer_result {
  FA_OBSERVER_OK = 0,
  FA_OBSERVER_INVALID_ARGUMENT = 1,
  FA_OBSERVER_BUFFER_TOO_SMALL = 2,
  FA_OBSERVER_UNSUPPORTED_PLATFORM = 3,
  FA_OBSERVER_MODULE_NOT_FOUND = 4,
  FA_OBSERVER_MODULE_HASH_MISMATCH = 5,
  FA_OBSERVER_ANCHOR_MISMATCH = 6,
  FA_OBSERVER_TARGET_BYTES_MISMATCH = 7,
  FA_OBSERVER_CALLBACK_NOT_READY = 8,
  FA_OBSERVER_DOBBY_HASH_MISMATCH = 9,
  FA_OBSERVER_DOBBY_LOAD_FAILED = 10,
  FA_OBSERVER_DOBBY_ABI_MISMATCH = 11,
  FA_OBSERVER_SELF_PIN_FAILED = 12,
  FA_OBSERVER_ALREADY_INSTALLED = 13,
  FA_OBSERVER_INSTALL_NOT_RETRYABLE = 14,
  FA_OBSERVER_PREPARE_FAILED = 15,
  FA_OBSERVER_INVALID_ORIGINAL = 16,
  FA_OBSERVER_COMMIT_FAILED = 17,
  FA_OBSERVER_CONTROL_EXCEPTION = 18,
  FA_OBSERVER_NOT_INSTALLED = 19,
  FA_OBSERVER_PATCH_NOT_OBSERVED = 20
} fa_observer_result;

typedef enum fa_observer_install_state {
  FA_OBSERVER_UNINSTALLED = 0,
  FA_OBSERVER_INSTALLING = 1,
  FA_OBSERVER_PREPARED = 2,
  FA_OBSERVER_COMMITTED = 3,
  FA_OBSERVER_PREPARATION_FAILED = 4,
  FA_OBSERVER_COMMIT_FAILED_STATE = 5
} fa_observer_install_state;

enum fa_observer_check_flags {
  FA_CHECK_MODULE_HASH = 1u << 0,
  FA_CHECK_ANCHOR = 1u << 1,
  FA_CHECK_TARGET_BYTES = 1u << 2,
  FA_CHECK_CALLBACK_READY = 1u << 3,
  FA_CHECK_DOBBY_HASH = 1u << 4,
  FA_CHECK_DOBBY_VERSION = 1u << 5,
  FA_CHECK_SELF_PINNED = 1u << 6,
  FA_CHECK_ORIGINAL_PUBLISHED = 1u << 7,
  FA_CHECK_PATCH_CHANGED_BYTES = 1u << 8
};

enum fa_observer_record_flags {
  FA_RECORD_KEYS_COUNT_KNOWN = 1u << 0,
  FA_RECORD_PAYLOAD_COUNT_KNOWN = 1u << 1,
  FA_RECORD_KEYS_COUNT_EXCEEDS_INT32 = 1u << 2,
  FA_RECORD_PAYLOAD_COUNT_EXCEEDS_INT32 = 1u << 3,
  FA_RECORD_KEYS_BYTE_SIZE_OVERFLOW = 1u << 4,
  FA_RECORD_THREAD_ID_UNKNOWN = 1u << 5
};

/* Fixed 48-byte, pack-8 layout. Counts are header values, never payload reads.
 * A missing *_COUNT_KNOWN flag means unknown; count=0 with the flag is known zero.
 */
typedef struct fa_observer_record {
  uint64_t call_sequence;
  uint64_t monotonic_ns;
  uint64_t native_thread_id;
  uint64_t keys_count;
  uint64_t payload_count;
  uint32_t flags;
  uint32_t reserved;
} fa_observer_record;

/* Fixed 88-byte, pack-8 layout. Concurrent counters are an approximate snapshot. */
typedef struct fa_observer_stats {
  uint32_t abi_version;
  uint32_t struct_size;
  uint32_t install_state;
  uint32_t capture_enabled;
  uint64_t invocation_count;
  uint64_t enqueued_count;
  uint64_t drained_count;
  uint64_t overflow_dropped;
  uint64_t contention_dropped;
  uint64_t capture_stopped_invocations;
  uint64_t in_flight_invocations;
  uint64_t queue_capacity;
  uint64_t queue_approx_size;
} fa_observer_stats;

/* Fixed 48-byte, pack-8 layout. Addresses are control-plane diagnostics only. */
typedef struct fa_observer_install_report {
  uint32_t abi_version;
  uint32_t struct_size;
  int32_t result;
  uint32_t install_state;
  uint32_t checks;
  int32_t prepare_result;
  int32_t commit_result;
  uint32_t reserved;
  uint64_t target_address;
  uint64_t original_address;
} fa_observer_install_report;

FA_OBSERVER_API uint32_t fa_observer_abi_version(void);
FA_OBSERVER_API uint64_t fa_observer_monotonic_ns(void);

/* anchor_export is the already-loaded exact setter export documented in README.
 * This function does not call the setter or any game business function.
 * Capture starts disabled. Install is process-lifetime and cannot be undone.
 */
FA_OBSERVER_API int fa_observer_install(void *anchor_export,
                                       const char *dobby_path_utf8,
                                       fa_observer_install_report *report,
                                       uint32_t report_size);
FA_OBSERVER_API int fa_observer_start_capture(void);
FA_OBSERVER_API int fa_observer_stop_capture(void);
FA_OBSERVER_API int fa_observer_drain(fa_observer_record *records,
                                     uint32_t capacity,
                                     uint32_t record_size,
                                     uint32_t *out_count);
FA_OBSERVER_API int fa_observer_get_stats(fa_observer_stats *stats,
                                         uint32_t stats_size);
FA_OBSERVER_API const char *fa_observer_result_message(int result);

#ifdef FA_OBSERVER_TESTING
/* Only compiled into independent test executables, absent from the dylib. */
FA_OBSERVER_API int fa_observer_test_install_toy(void *target,
                                                const char *dobby_path_utf8,
                                                fa_observer_install_report *report,
                                                uint32_t report_size);
#endif

#ifdef __cplusplus
}
#endif
#endif
