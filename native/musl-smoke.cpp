#include "include/core/SkBitmap.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkFont.h"
#include "include/core/SkFontMgr.h"
#include "include/core/SkFontStyle.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkPaint.h"

extern "C" int verify_skia_render()
{
    auto font_manager = SkFontMgr::RefDefault();
    if (!font_manager)
        return 1;

    sk_sp<SkTypeface> typeface(font_manager->matchFamilyStyle("DejaVu Sans", SkFontStyle()));
    if (!typeface)
        return 2;

    SkBitmap bitmap;
    if (!bitmap.tryAllocPixels(SkImageInfo::MakeN32Premul(160, 64)))
        return 3;

    SkCanvas canvas(bitmap);
    canvas.clear(SK_ColorTRANSPARENT);
    SkPaint paint;
    paint.setColor(SK_ColorWHITE);
    SkFont font(typeface, 28.0f);
    canvas.drawString("Avalonia", 8.0f, 44.0f, font, paint);

    for (int y = 0; y < bitmap.height(); ++y)
    {
        for (int x = 0; x < bitmap.width(); ++x)
        {
            if (SkColorGetA(*bitmap.getAddr32(x, y)) != 0)
                return 0;
        }
    }

    return 4;
}
