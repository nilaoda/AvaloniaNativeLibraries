#include <cstdio>

#ifdef VERIFY_SKIA
extern "C" int sk_version_get_milestone();
extern "C" void* sk_bitmap_new();
extern "C" void sk_bitmap_destructor(void*);
#endif
#ifdef VERIFY_HARFBUZZ
extern "C" void hb_version(unsigned*, unsigned*, unsigned*);
extern "C" void* hb_buffer_create();
extern "C" void hb_buffer_destroy(void*);
#endif
#ifdef VERIFY_ANGLE
extern "C" void* __stdcall EGL_GetProcAddress(const char*);
#endif
#ifdef VERIFY_AVALONIA
extern "C" void* CreateAvaloniaNative();
#endif

int main()
{
#ifdef VERIFY_SKIA
    if (sk_version_get_milestone() != 88) return 1;
    auto bitmap = sk_bitmap_new();
    if (!bitmap) return 2;
    sk_bitmap_destructor(bitmap);
#endif
#ifdef VERIFY_HARFBUZZ
    unsigned major = 0, minor = 0, micro = 0;
    hb_version(&major, &minor, &micro);
    if (major != 8 || minor != 3 || micro != 1) return 3;
    auto buffer = hb_buffer_create();
    if (!buffer) return 4;
    hb_buffer_destroy(buffer);
#endif
#ifdef VERIFY_ANGLE
    if (!EGL_GetProcAddress("glGetString")) return 5;
#endif
#ifdef VERIFY_AVALONIA
    if (!CreateAvaloniaNative()) return 6;
#endif
    std::puts("Native static libraries verified.");
    return 0;
}
