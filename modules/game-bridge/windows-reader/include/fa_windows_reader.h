#ifndef FA_WINDOWS_READER_H
#define FA_WINDOWS_READER_H
#include <stdint.h>
#if defined(_WIN32)
#define FA_WIN_API __declspec(dllexport)
#else
#define FA_WIN_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* ABI v1, natural 8-byte alignment. No borrowed pointers or allocated output.
 * result: 0 success, 1 unsupported, 2 invalid, 3 unreadable, 4 malformed,
 * 5 limit, 6 unavailable. Success inventories a module, NOT a supported game
 * build or verified business layout. PE timestamp/checksum are NOT a hash.
 */
typedef struct fa_win_section_v1 {
  char name[8]; /* Not necessarily NUL-terminated. */
  uint32_t rva, virtual_size, raw_size, characteristics;
  uint64_t runtime_address;
} fa_win_section_v1;
typedef struct fa_win_module_v1 {
  uint32_t version, struct_size;
  int32_t result;
  uint32_t machine, timestamp, checksum, image_size, headers_size;
  uint64_t runtime_base, preferred_base;
  uint32_t section_count, reserved;
  fa_win_section_v1 sections[32];
} fa_win_module_v1;
/* Host supplies an export of an explicitly known ALREADY LOADED module.
 * Does not load a DLL, invoke game functions, patch memory or open a process.
 * Caller owns report; size mismatch leaves report untouched. No address-read
 * export is offered. Supported-build allowlisting belongs to the future host.
 */
FA_WIN_API int32_t fa_win_inspect_module_v1(
    const void* known_anchor, fa_win_module_v1* report, uint32_t report_size);
#ifdef __cplusplus
}
#endif
#endif
