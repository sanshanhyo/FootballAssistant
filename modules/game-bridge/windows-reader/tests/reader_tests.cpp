#include "reader.hpp"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <vector>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif
using namespace fa::win;
void Check(bool ok,const char* text) { if (!ok) { std::cerr<<text<<'\n'; std::exit(1); } }
void Put(std::vector<std::byte>& b,size_t offset,uint64_t value,size_t n=4) {
  for(size_t i=0;i<n;++i) b[offset+i]=std::byte((value>>(i*8))&255);
}
std::vector<std::byte> Fixture() {
  std::vector<std::byte> b(512);
  Put(b,0,0x5a4d,2); Put(b,60,64); Put(b,64,0x4550); Put(b,68,0x8664,2);
  Put(b,70,1,2); Put(b,72,123); Put(b,84,112,2); Put(b,88,0x20b,2);
  Put(b,112,0x140000000,8); Put(b,144,0x2000); Put(b,148,512);
  std::memcpy(b.data()+200,".text",5); Put(b,208,100); Put(b,212,0x1000);
  Put(b,216,512); Put(b,236,0x60000020); return b;
}
void ParserTests() {
  auto b=Fixture(); fa_win_module_v1 m{};
  Check(ParsePe(b,0x180000000,m)==Result::ok,"valid PE");
  Check(m.machine==0x8664 && m.timestamp==123 && m.runtime_base==0x180000000 &&
        m.sections[0].runtime_address==0x180001000 && m.preferred_base==0x140000000,"PE values");
  for(size_t size=0;size<b.size();++size) {
    Check(ParsePe(std::span(b).first(size),0x180000000,m)!=Result::ok,"truncated PE accepted");
    Check(m.section_count==0 && m.runtime_base==0,"partial parse published");
  }
  const std::array<std::pair<size_t,uint64_t>,10> bad={{{0,0},{60,UINT32_MAX},{64,0},{68,0x14c},
    {70,33},{84,111},{88,0x10b},{144,256},{148,65537},{212,0xfffffff0}}};
  for(auto [offset,value]:bad) {
    auto broken=b; Put(broken,offset,value,offset==68||offset==70||offset==84||offset==88?2:4);
    Check(ParsePe(broken,0x180000000,m)!=Result::ok,"malformed PE accepted");
  }
  Check(ParsePe(b,UINT64_MAX-10,m)!=Result::ok,"runtime overflow");
  auto broken=b; Put(broken,112,UINT64_MAX-10,8);
  Check(ParsePe(broken,0x180000000,m)!=Result::ok,"preferred overflow");
  Check(!ValidRange(UINT64_MAX,1),"range overflow");
  fa_win_module_v1 report{}; report.version=123;
  Check(fa_win_inspect_module_v1(nullptr,&report,1)==2 && report.version==123,"ABI bad size");
  Check(fa_win_inspect_module_v1(nullptr,&report,sizeof(report))==2 && report.version==1 &&
        report.struct_size==1080 && report.section_count==0,"ABI null anchor");
}
struct Fake {
  uint32_t protection=4,state=0x1000,queries=0,copies=0;
  uint64_t region_size=4096; bool query_fail=false,copy_fail=false,short_copy=false,hole=false;
};
bool Query(void* context,uint64_t address,Region& out) noexcept {
  auto& f=*static_cast<Fake*>(context); ++f.queries;
  if(f.query_fail)return false;
  out={address+(f.hole?1:0),f.region_size,f.state,f.protection}; return true;
}
bool Copy(void* context,uint64_t,std::span<std::byte> out,size_t& n) noexcept {
  auto& f=*static_cast<Fake*>(context); ++f.copies;
  std::fill(out.begin(),out.end(),std::byte{42}); n=out.size()-(f.short_copy?1:0); return !f.copy_fail;
}
void MemoryTests() {
  std::array<std::byte,128> out{}; Fake f; Backend b{&f,Query,Copy};
  Check(Read(b,4096,out)==Result::ok && f.copies==1 && out[0]==std::byte{42},"exact fake read");
  f=Fake{}; f.region_size=64;
  Check(Read(b,4096,out)==Result::ok && f.queries==2 && f.copies==1,"multi-region read");
  f=Fake{}; f.query_fail=true;
  Check(Read(b,4096,out)==Result::unreadable && !f.copies,"query failed");
  f=Fake{};
  Check(Read(b,reinterpret_cast<uint64_t>(out.data()),out)==Result::invalid && !f.queries,"source aliases output");
  for(auto protection:{uint32_t(1),uint32_t(0x104),uint32_t(0x10),uint32_t(0)}) {
    f=Fake{}; f.protection=protection;
    Check(Read(b,4096,out)==Result::unreadable && f.copies==0,"unsafe page copied");
  }
  for(auto state:{uint32_t(0x2000),uint32_t(0x10000)}) {
    f=Fake{}; f.state=state; Check(Read(b,4096,out)==Result::unreadable && !f.copies,"uncommitted copied");
  }
  for(int failure=0;failure<2;++failure) {
    f=Fake{}; f.short_copy=failure==0; f.copy_fail=failure==1;
    Check(Read(b,4096,out)==Result::unreadable,"short/failed copy accepted");
    for(auto value:out) Check(value==std::byte{},"partial copy exposed");
  }
  f=Fake{}; f.region_size=1;
  Check(Read(b,4096,out)==Result::limit && f.queries==64 && !f.copies,"query bound");
  f=Fake{}; f.region_size=0; Check(Read(b,4096,out)==Result::unreadable,"nonprogress region");
  f=Fake{}; f.hole=true; Check(Read(b,4096,out)==Result::unreadable,"hole accepted");
  f=Fake{}; Check(Read(b,UINT64_MAX-1,out)==Result::invalid && !f.queries,"overflow queried");
  std::vector<std::byte> huge(MaxRead+1);
  Check(Read(b,4096,huge)==Result::invalid,"read byte budget");
}
#if defined(_WIN32) && defined(_WIN64)
void Anchor() {}
void NativeTests() {
  fa_win_module_v1 module{};
  Check(fa_win_inspect_module_v1(reinterpret_cast<const void*>(&Anchor),&module,sizeof(module))==0 &&
        module.machine==0x8664 && module.section_count>0,"own native module");
  Check(fa_win_inspect_module_v1(reinterpret_cast<const void*>(1),&module,sizeof(module))==6,"missing module");
  SYSTEM_INFO info{}; GetSystemInfo(&info); const auto page=info.dwPageSize;
  auto* memory=static_cast<std::byte*>(VirtualAlloc(nullptr,size_t(page)*2,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
  Check(memory!=nullptr,"toy allocation"); std::memset(memory,0x5a,size_t(page)*2);
  std::array<std::byte,32> out{};
  Check(ReadOwn(reinterpret_cast<uint64_t>(memory),out)==Result::ok && out[0]==std::byte{0x5a},"native exact read");
  DWORD old=0;
  Check(VirtualProtect(memory+page,page,PAGE_NOACCESS,&old)!=0,"toy noaccess");
  Check(ReadOwn(reinterpret_cast<uint64_t>(memory+page-16),out)==Result::unreadable,"cross noaccess");
  for(auto v:out) Check(v==std::byte{},"noaccess output");
  Check(VirtualProtect(memory+page,page,PAGE_READWRITE|PAGE_GUARD,&old)!=0,"toy guard");
  Check(ReadOwn(reinterpret_cast<uint64_t>(memory+page),out)==Result::unreadable,"guard copied");
  MEMORY_BASIC_INFORMATION region{};
  Check(VirtualQuery(memory+page,&region,sizeof(region))==sizeof(region) &&
        (region.Protect&PAGE_GUARD)!=0,"guard was consumed");
  Check(VirtualFree(memory,0,MEM_RELEASE)!=0,"toy release");
  Check(ReadOwn(reinterpret_cast<uint64_t>(memory),out)==Result::unreadable,"unmapped copied");
}
#endif
int main() {
  ParserTests(); MemoryTests();
#if defined(_WIN32) && defined(_WIN64)
  NativeTests(); std::cout<<"portable + Windows native toy tests passed\n";
#else
  std::cout<<"portable parser/fake backend passed; Windows native tests NOT RUN\n";
#endif
}
