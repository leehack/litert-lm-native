#include "bridge/android_gpu_safety.h"
#include <cassert>
#include <fcntl.h>
#include <iostream>
#include <sys/mman.h>
#include <unistd.h>

using namespace litert_lm_native;
int main(int argc, char **argv) {
  const GpuFacts affected{0x5143, 0x43051401, 2150604839u, 134217728};
  GpuProbe probe{true, {affected}};
  auto restriction = Qwen3GpuRestriction(FixtureIdentity::kQwen3, probe);
  assert(restriction.find("155582464") != std::string::npos);
  assert(restriction.find("134217728") != std::string::npos);
  assert(restriction.find("selected adapter") != std::string::npos);
  assert(restriction.find("Use CPU") != std::string::npos);
  assert(Qwen3GpuRestriction(FixtureIdentity::kOther, probe).empty());
  for (int field = 0; field < 3; ++field) {
    auto near = affected;
    if (field == 0)
      ++near.vendor;
    if (field == 1)
      ++near.device;
    if (field == 2)
      ++near.driver;
    assert(
        Qwen3GpuRestriction(FixtureIdentity::kQwen3, {true, {near}}).empty());
  }
  for (uint64_t limit : {0ull, 134217728ull, 155582464ull, 4294967295ull}) {
    auto same_driver = affected;
    same_driver.storage_limit = limit;
    // A larger limit does not clear the independent historical shader-crash
    // restriction for this exact tuple.
    assert(!Qwen3GpuRestriction(FixtureIdentity::kQwen3, {true, {same_driver}})
                .empty());
  }
  assert(!Qwen3GpuRestriction(FixtureIdentity::kQwen3, {}).empty());
  assert(!Qwen3GpuRestriction(FixtureIdentity::kQwen3, {true, {{0, 0, 0, 0}}})
              .empty());
  assert(!Qwen3GpuRestriction(FixtureIdentity::kQwen3, {true, {}}).empty());
  assert(!Qwen3GpuRestriction(FixtureIdentity::kQwen3,
                              {true, {affected, affected}})
              .empty());
  assert(!Qwen3GpuRestriction(FixtureIdentity::kUnreadable, probe).empty());
  assert(IdentifyQwen3File(-1) == FixtureIdentity::kUnreadable);
  assert(IdentifyQwen3Bytes(nullptr, kQwen3FixtureSize) ==
         FixtureIdentity::kUnreadable);
  assert(IdentifyQwen3Bytes(nullptr, 0) == FixtureIdentity::kOther);
  if (argc == 2) {
    const int fd = open(argv[1], O_RDONLY);
    assert(fd >= 0);
    assert(lseek(fd, 7, SEEK_SET) == 7);
    assert(IdentifyQwen3File(fd) == FixtureIdentity::kQwen3);
    assert(lseek(fd, 0, SEEK_CUR) == 7);
    void *mapped = mmap(nullptr, kQwen3FixtureSize, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE, fd, 0);
    assert(mapped != MAP_FAILED);
    assert(IdentifyQwen3Bytes(mapped, kQwen3FixtureSize) ==
           FixtureIdentity::kQwen3);
    static_cast<unsigned char *>(mapped)[0] ^= 1;
    assert(IdentifyQwen3Bytes(mapped, kQwen3FixtureSize) ==
           FixtureIdentity::kOther);
    munmap(mapped, kQwen3FixtureSize);
    char directory[] = "/tmp/litert_gpu_model_XXXXXX";
    assert(mkdtemp(directory));
    const std::string link = std::string(directory) + "/renamed-model";
    assert(symlink(argv[1], link.c_str()) == 0);
    const int pinned = open(link.c_str(), O_RDONLY);
    assert(pinned >= 0);
    assert(unlink(link.c_str()) == 0);
    assert(symlink("/dev/null", link.c_str()) == 0);
    assert(IdentifyQwen3File(pinned) == FixtureIdentity::kQwen3);
    close(pinned);
    unlink(link.c_str());
    rmdir(directory);
    close(fd);
    std::cout
        << "Exact fixture SHA and size verified through retained descriptor\n";
  }
  std::cout << "Android GPU narrow-policy tests passed\n";
}
