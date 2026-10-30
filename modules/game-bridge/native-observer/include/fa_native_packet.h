#ifndef FA_NATIVE_PACKET_H
#define FA_NATIVE_PACKET_H

#include "fa_native_observer.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
  FA_PACKET_ABI_VERSION = 1,
  FA_PACKET_MAX_KEYS = 4096,
  FA_PACKET_MAX_PAYLOAD_BYTES = 65536,
  FA_PACKET_MAX_TOTAL_BYTES = 98304
};

typedef enum fa_packet_result {
  FA_PACKET_OK = 0,
  FA_PACKET_INVALID_ARGUMENT = 100,
  FA_PACKET_UNSUPPORTED_VERSION = 101,
  FA_PACKET_BUFFER_TOO_SMALL = 102,
  FA_PACKET_NOT_INSTALLED = 103,
  FA_PACKET_LEGACY_CAPTURE_DISABLED = 104,
  FA_PACKET_BUSY = 105,
  FA_PACKET_WRONG_CAPTURE_ID = 106,
  FA_PACKET_NOT_READY = 107,
  FA_PACKET_CANCEL_PENDING = 108,
  FA_PACKET_CANCELLED_RESULT = 109,
  FA_PACKET_NEEDS_RELEASE = 110,
  FA_PACKET_ALREADY_READY = 111,
  FA_PACKET_NO_CAPTURE = 112,
  FA_PACKET_ID_EXHAUSTED = 113,
  FA_PACKET_CONTROL_EXCEPTION = 114
} fa_packet_result;

typedef enum fa_packet_state {
  FA_PACKET_IDLE = 0,
  FA_PACKET_ARMED = 1,
  FA_PACKET_WRITING = 2,
  FA_PACKET_CANCELLING = 3,
  FA_PACKET_READY = 4,
  FA_PACKET_CANCELLED = 5
} fa_packet_state;

enum fa_packet_manifest_flags {
  FA_PACKET_COUNTS_KNOWN = 1u << 0,
  FA_PACKET_COMPLETE = 1u << 1,
  FA_PACKET_ORIGINAL_RESULT_UNKNOWN = 1u << 2,
  FA_PACKET_LEGACY_DISABLED = 1u << 3,
  FA_PACKET_CANCEL_REQUESTED = 1u << 4
};

typedef enum fa_packet_skip_reason {
  FA_PACKET_SKIP_NONE = 0,
  FA_PACKET_SKIP_NULL_HEADER = 1,
  FA_PACKET_SKIP_KEYS_BELOW_MINIMUM = 2,
  FA_PACKET_SKIP_PAYLOAD_BELOW_MINIMUM = 3,
  FA_PACKET_SKIP_KEYS_OVER_CAP = 4,
  FA_PACKET_SKIP_PAYLOAD_OVER_CAP = 5,
  FA_PACKET_SKIP_KEYS_SIZE_OVERFLOW = 6,
  FA_PACKET_SKIP_TOTAL_OVER_CAP = 7,
  FA_PACKET_SKIP_NULL_KEYS_DATA = 8,
  FA_PACKET_SKIP_NULL_PAYLOAD_DATA = 9,
  FA_PACKET_SKIP_CANCELLED = 10,
  FA_PACKET_SKIP_SOURCE_RANGE_OVERFLOW = 11,
  FA_PACKET_SKIP_UNREADABLE_KEYS = 12,
  FA_PACKET_SKIP_UNREADABLE_PAYLOAD = 13
} fa_packet_skip_reason;

/* 48 bytes, pack 8. Version/size/flags/reserved are checked before arming. */
typedef struct fa_packet_request_v1 {
  uint32_t version;
  uint32_t struct_size;
  uint32_t min_keys;
  uint32_t max_keys;
  uint32_t min_payload_bytes;
  uint32_t max_payload_bytes;
  uint32_t max_total_bytes;
  uint32_t flags;
  uint64_t reserved0;
  uint64_t reserved1;
} fa_packet_request_v1;

/* 112 bytes, pack 8. Counts/bytes are unknown unless COUNTS_KNOWN is set.
 * COMPLETE means both owned buffers were fully copied, not that the game's
 * original receiver successfully parsed or processed the packet.
 */
typedef struct fa_packet_manifest_v1 {
  uint32_t version;
  uint32_t struct_size;
  uint32_t state;
  uint32_t flags;
  uint64_t capture_id;
  uint64_t call_sequence;
  uint64_t monotonic_ns;
  uint64_t native_thread_id;
  uint64_t original_keys_count;
  uint64_t original_payload_count;
  uint64_t copied_keys_bytes;
  uint64_t copied_payload_bytes;
  uint64_t checked_packets;
  uint64_t skipped_packets;
  uint32_t last_skip_reason;
  uint32_t reserved;
  uint64_t busy_skipped_total;
} fa_packet_manifest_v1;

FA_OBSERVER_API uint32_t fa_observer_packet_abi_version(void);
FA_OBSERVER_API int fa_observer_packet_default_request(
    fa_packet_request_v1 *request, uint32_t request_size);
FA_OBSERVER_API int fa_observer_packet_arm(
    const fa_packet_request_v1 *request, uint32_t request_size,
    uint64_t *out_capture_id);
/* capture_id=0 queries the current slot; other operations require a nonzero ID. */
FA_OBSERVER_API int fa_observer_packet_get_manifest(
    uint32_t version, uint64_t capture_id, fa_packet_manifest_v1 *manifest,
    uint32_t manifest_size);
/* Does not release. Destinations must be separate, valid owned buffers. */
FA_OBSERVER_API int fa_observer_packet_copy(
    uint32_t version, uint64_t capture_id, void *keys_buffer,
    uint64_t keys_capacity_bytes, void *payload_buffer,
    uint64_t payload_capacity_bytes, fa_packet_manifest_v1 *manifest,
    uint32_t manifest_size);
FA_OBSERVER_API int fa_observer_packet_cancel(uint32_t version,
                                             uint64_t capture_id);
FA_OBSERVER_API int fa_observer_packet_release(uint32_t version,
                                              uint64_t capture_id);
FA_OBSERVER_API const char *fa_observer_packet_result_message(int result);

#ifdef __cplusplus
}
#endif
#endif
