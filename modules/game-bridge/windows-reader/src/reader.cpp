#include "reader.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif
namespace fa::win {
namespace {
uint16_t U16(std::span<const std::byte> b, size_t p) noexcept {
  return uint16_t(std::to_integer<uint8_t>(b[p])) | uint16_t(std::to_integer<uint8_t>(b[p+1]) << 8);
}
uint32_t U32(std::span<const std::byte> b, size_t p) noexcept {
  return uint32_t(U16(b,p)) | (uint32_t(U16(b,p+2)) << 16);
}
uint64_t U64(std::span<const std::byte> b, size_t p) noexcept {
  return uint64_t(U32(b,p)) | (uint64_t(U32(b,p+4)) << 32);
}
Result Parse(std::span<const std::byte> b, uint64_t base, fa_win_module_v1& out) noexcept {
  if (base == 0 || b.size() < 64 || U16(b,0) != 0x5a4d) return Result::malformed;
  const auto pe = U32(b,60);
  if (pe < 64 || pe > MaxRead - 24 || pe > b.size() - 24) return Result::malformed;
  if (U32(b,pe) != 0x4550) return Result::malformed;
  if (U16(b,pe+4) != 0x8664) return Result::unsupported;
  const auto count = U16(b,pe+6), optional = U16(b,pe+20);
  if (count == 0 || count > 32) return Result::limit;
  const size_t opt = pe + 24;
  if (optional < 112 || optional > b.size() - opt || U16(b,opt) != 0x20b) return Result::malformed;
  if (U32(b,opt+108) > (optional - 112u) / 8u) return Result::malformed;
  const auto image_size = U32(b,opt+56), headers_size = U32(b,opt+60);
  const auto preferred = U64(b,opt+24);
  const size_t sections = opt + optional;
  if (uint64_t(count)*40 > b.size()-sections || headers_size > MaxRead ||
      headers_size > b.size() || headers_size < sections + uint64_t(count)*40 ||
      image_size < headers_size || image_size == 0 || !ValidRange(base,image_size) ||
      !ValidRange(preferred,image_size)) return Result::malformed;
  out.machine = 0x8664; out.timestamp = U32(b,pe+8); out.checksum = U32(b,opt+64);
  out.image_size = image_size; out.headers_size = headers_size;
  out.runtime_base = base; out.preferred_base = preferred; out.section_count = count;
  for (uint32_t i=0; i<count; ++i) {
    const size_t pos = sections + i*40;
    auto& s = out.sections[i]; std::memcpy(s.name,b.data()+pos,8);
    s.virtual_size=U32(b,pos+8); s.rva=U32(b,pos+12); s.raw_size=U32(b,pos+16);
    s.characteristics=U32(b,pos+36);
    const uint64_t extent = std::max(s.virtual_size,s.raw_size);
    if (s.rva > image_size || extent > image_size-s.rva ||
        (extent != 0 && s.rva < headers_size)) return Result::malformed;
    for (uint32_t j=0; j<i; ++j) {
      const auto& earlier=out.sections[j];
      const uint64_t previous=std::max(earlier.virtual_size,earlier.raw_size);
      if (extent && previous && s.rva < uint64_t(earlier.rva)+previous &&
          earlier.rva < uint64_t(s.rva)+extent) return Result::malformed;
    }
    s.runtime_address=base+s.rva;
  }
  return Result::ok;
}
#if defined(_WIN32)
bool Query(void*, uint64_t address, Region& region) noexcept {
  MEMORY_BASIC_INFORMATION info{};
  if (VirtualQuery(reinterpret_cast<const void*>(address), &info, sizeof(info)) != sizeof(info)) return false;
  region={reinterpret_cast<uint64_t>(info.BaseAddress), info.RegionSize, info.State, info.Protect}; return true;
}
bool Copy(void*, uint64_t address, std::span<std::byte> output, size_t& copied) noexcept {
  SIZE_T n=0;
  const bool ok=ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(address),
                                output.data(), output.size(), &n) != 0;
  copied=n; return ok;
}
#endif
}
bool ValidRange(uint64_t address,uint64_t size) noexcept { return size <= UINT64_MAX-address; }
bool Readable(const Region& r) noexcept {
  // MEM_COMMIT and readable PAGE_* values; guards rejected before RPM so no
  // intentional guard-page consumption. Max/allocation protections aren't used.
  if (r.state != 0x1000 || (r.protection & 0x100) != 0) return false;
  switch (r.protection & 0xff) {
    case 0x02: case 0x04: case 0x08: case 0x20: case 0x40: case 0x80: return true;
    default: return false;
  }
}
Result Read(const Backend& backend,uint64_t address,std::span<std::byte> out) noexcept {
  if (!backend.query || !backend.copy || address==0 || out.empty() || out.size()>MaxRead ||
      !ValidRange(address,out.size())) return Result::invalid;
  const auto destination=reinterpret_cast<uint64_t>(out.data());
  if (!ValidRange(destination,out.size()) ||
      (address < destination+out.size() && destination < address+out.size())) return Result::invalid;
  std::fill(out.begin(),out.end(),std::byte{});
  auto cursor=address; const auto end=address+out.size();
  for (uint32_t calls=0; cursor<end; ++calls) {
    if (calls==MaxQueries) return Result::limit;
    Region r{};
    if (!backend.query(backend.context,cursor,r) || !Readable(r) || r.size==0 ||
        !ValidRange(r.base,r.size) || r.base>cursor || cursor-r.base>=r.size) return Result::unreadable;
    cursor=std::min(end,r.base+r.size);
  }
  size_t copied=0;
  if (backend.copy(backend.context,address,out,copied) && copied==out.size()) return Result::ok;
  std::fill(out.begin(),out.end(),std::byte{}); return Result::unreadable;
}
Result ReadOwn(uint64_t address,std::span<std::byte> out) noexcept {
#if defined(_WIN32) && defined(_WIN64)
  return Read(Backend{nullptr,Query,Copy},address,out);
#else
  (void)address; (void)out; return Result::unsupported;
#endif
}
Result ParsePe(std::span<const std::byte> bytes,uint64_t base,fa_win_module_v1& out) noexcept {
  fa_win_module_v1 candidate{}; const auto result=Parse(bytes,base,candidate);
  out=result==Result::ok ? candidate : fa_win_module_v1{};
  out.version=1; out.struct_size=sizeof(out); out.result=static_cast<int32_t>(result); return result;
}
Result InspectKnownModule(const void* anchor,fa_win_module_v1& out) noexcept {
  out={};
  if (!anchor) return Result::invalid;
#if defined(_WIN32) && defined(_WIN64)
  HMODULE module=nullptr;
  // Acquire a reference to an existing image, preventing concurrent unload
  // during copy. Never LoadLibrary or invoke an anchor. Balance only our reference.
  if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                          reinterpret_cast<LPCWSTR>(anchor), &module)) return Result::unavailable;
  struct Release { HMODULE handle; ~Release() { FreeLibrary(handle); } } release{module};
  const auto base=reinterpret_cast<uint64_t>(module);
  std::array<std::byte,MaxRead> bytes{};
  auto status=ReadOwn(base,std::span(bytes).first(64)); if (status!=Result::ok) return status;
  if (U16(bytes,0)!=0x5a4d) return Result::malformed;
  const auto pe=U32(bytes,60);
  if (pe<64 || pe>MaxRead-24-112) return Result::limit;
  const size_t minimum=pe+24+112;
  status=ReadOwn(base,std::span(bytes).first(minimum)); if (status!=Result::ok) return status;
  if (U32(bytes,pe)!=0x4550 || U16(bytes,pe+24)!=0x20b) return Result::malformed;
  const auto headers=U32(bytes,pe+24+60);
  if (headers<minimum || headers>MaxRead) return Result::limit;
  status=ReadOwn(base,std::span(bytes).first(headers)); if (status!=Result::ok) return status;
  return ParsePe(std::span(bytes).first(headers),base,out);
#else
  return Result::unsupported;
#endif
}
}
static_assert(sizeof(fa_win_section_v1)==32);
static_assert(sizeof(fa_win_module_v1)==1080);
static_assert(offsetof(fa_win_module_v1,sections)==56);
extern "C" int32_t fa_win_inspect_module_v1(const void* anchor,fa_win_module_v1* out,uint32_t size) {
  using namespace fa::win;
  if (!out || size!=sizeof(*out)) return static_cast<int32_t>(Result::invalid);
  const auto result=InspectKnownModule(anchor,*out);
  if (result!=Result::ok) *out={};
  out->version=1; out->struct_size=sizeof(*out); out->result=static_cast<int32_t>(result);
  return out->result;
}
