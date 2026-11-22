#include <dlfcn.h>
#include <string.h>

typedef void *(*loader_function)(const char *, int);

/* 仅将静态 Skia 的显式加载请求映射到主程序，其余请求交回系统加载器。 */
__attribute__((visibility("hidden")))
void *dlopen(const char *path, int mode)
{
    loader_function system_loader = (loader_function)dlsym(RTLD_NEXT, "dlopen");
    if (!system_loader)
        return 0;
    if (path)
    {
        const char *name = strrchr(path, '/');
        name = name ? name + 1 : path;
        if (strcmp(name, "libSkiaSharp") == 0 || strcmp(name, "libSkiaSharp.dylib") == 0)
            return system_loader(0, mode);
    }
    return system_loader(path, mode);
}
