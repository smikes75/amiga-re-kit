/* What Moira takes from vAmiga, so that its source compiles outside the emulator (arek difftest). */
#pragma once
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define fatalError do { fprintf(stderr, "Moira: fatal at %s:%d\n", __FILE__, __LINE__); abort(); } while (0)
namespace vamiga {
class Amiga;
class SubComponent {
public:
    explicit SubComponent(Amiga &) {}
    virtual ~SubComponent() = default;
};
}
