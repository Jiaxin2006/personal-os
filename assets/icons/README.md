# Personal OS icon

Generated with the built-in imagegen tool on 2026-11-06. The original generated
concept is `personal-os-icon-v2.png`; the final full-bleed source for the system's
own icon mask is `personal-os-icon-v3.png`. `tools/prepare_app_icon.py` masks it
into the rounded 824px macOS tile (1024px canvas, soft shadow) and writes `AppIcon.png`
and `AppIcon.icns`: macOS does not mask the bundle icon or the Dock icon set at launch,
so the unmasked square would show with hard corners.

Visual direction: warm ivory rounded square, deep-indigo continuous p/time-loop
monogram, one muted amber progress marker. The calm palette matches the app's
paper-and-ink theme. The prior programmatic design remains in `tools/make_icon.swift`.

Prompt:

Create a final production macOS app icon for an original personal time-and-goals application named Personal OS. One icon only, centered, square 1024x1024 composition. Transparent outer canvas. A warm ivory rounded-square macOS tile, beautifully proportioned on the standard icon grid with generous transparent margins and a soft realistic contact shadow. Within it, a single bold deep-indigo sculptural monogram: an abstract lowercase p formed by a vertical rounded stroke flowing into a nearly closed circular loop, evocative of a time cycle and a personal path. A small muted amber circular dot sits at the upper-right break of the loop as an intentional progress marker. Refined Japanese stationery meets contemporary macOS enamel icon design; soft beveled depth, matte ceramic finish, precise geometry, subtle gentle highlights, warm white and rich indigo dominant, tiny amber accent. Strong clean silhouette, spacious composition, immediately recognizable at 32 pixels, premium and calm. No words, no printed letters, no numbers, no ticks or small details, no extra symbols, no border around the canvas, no perspective, no mockup or background scene. Face-on app icon artwork, ready to use as AppIcon.

Final adaptation prompt (built-in imagegen edit):

Edit this exact Personal OS icon artwork for a macOS icon pipeline that applies its own outer mask. Preserve the exact deep-indigo sculptural p/time-loop monogram, the amber circular progress marker, their relative positions, and the understated matte enamel material. Replace the entire rounded-square ivory tile and transparent outer canvas with one completely opaque, continuous, flat warm-ivory square background extending all the way to all four image edges. Remove the outer tile boundary, rounded tile corners, bevel and the external contact shadow; keep only the monogram's own very subtle dimensional shading. This is an unmasked full-bleed source asset, not a finished tile mockup: no inset tile, no outer rounded square, no transparent margin, no border, no background scene. Make the mark large and balanced with about 18 percent clear space from image sides, still very legible at 32 pixels. Square 1024x1024. No text. Keep the design identity unchanged.
