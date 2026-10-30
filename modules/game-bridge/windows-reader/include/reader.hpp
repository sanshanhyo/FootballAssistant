#pragma once
#include "fa_windows_reader.h"
#include <cstddef>
#include <cstdint>
#include <span>
namespace fa::win {
enum class Result : int32_t { ok, unsupported, invalid, unreadable, malformed, limit, unavailable };
constexpr size_t MaxRead = 65536;
constexpr uint32_t MaxQueries = 64;
struct Region { uint64_t base{}, size{}; uint32_t state{}, protection{}; };
// Injectable internal backend for portable tests; no external address endpoint.
struct Backend {
  void* context{};
  bool (*query)(void*, uint64_t, Region&) noexcept{};
  bool (*copy)(void*, uint64_t, std::span<std::byte>, size_t&) noexcept{};
};
bool ValidRange(uint64_t address, uint64_t size) noexcept;
bool Readable(const Region&) noexcept;
// All source ranges queried before copy; valid requests either read fully or
// clear output. Invalid requests (including source/destination overlap) do not
// touch output. The caller supplies its own writable destination storage.
// Fixed byte/query bounds. Race-safe failure handling, not atomic object state.
Result Read(const Backend&, uint64_t address, std::span<std::byte>) noexcept;
Result ReadOwn(uint64_t address, std::span<std::byte>) noexcept;
Result ParsePe(std::span<const std::byte>, uint64_t runtime_base, fa_win_module_v1&) noexcept;
Result InspectKnownModule(const void*, fa_win_module_v1&) noexcept;
}
