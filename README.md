# amazing-posters

**250 production-grade poster prompt specs** — structured text-to-image prompts, each paired with a
finished example. Free to copy, adapt and ship.

[![](https://img.shields.io/badge/site-posterlet.com-111)](https://posterlet.com)
[![](https://img.shields.io/badge/prompts-250-e02020)](data/posters.jsonl)
[![](https://img.shields.io/badge/license-CC%20BY%204.0-blue)](LICENSE)

[![](https://files.posterlet.com/assets/generated/md/zjh4ho2izbhi.webp)](https://posterlet.com/poster/halloween-party-recap-social-poster)

## What this is

Every poster on [posterlet.com](https://posterlet.com) is generated from a structured prompt spec rather than a one-line
description. Posterlet is an SI (superintelligence) poster generator, and this repository publishes 250
of the specs behind its output — the exact text that produced each image, with no abridging — so you can see
how layout, color, typography and subject are constrained separately, and copy the patterns into your own
pipeline.

Each spec is written in English and split into sections, which is what makes the output reproducible:

| Section | What it controls |
|---|---|
| `[Format]` | aspect ratio, medium, overall style, what the image is for |
| `[Colors]` | named palette with hex values, contrast and background treatment |
| `[Layout]` | where each block sits, grid, hierarchy, negative space |
| `[Subject]` | people, products, scenes — wardrobe, pose, lighting |
| `[Headline]` / `[Copy]` | the literal text rendered into the image |
| `[Mood]` | tonal direction that ties the choices together |

The infographic collection is the exception: those specs are a single narrative paragraph, because a
whole-page diagram is easier to specify as one description than as independent blocks.

## Galleries

| Collection | Prompts |
|---|---|
| [Halloween Posters](gallery/halloween.md) | 39 |
| [Black Friday & Cyber Monday](gallery/black-friday.md) | 39 |
| [Christmas & Holiday](gallery/christmas.md) | 38 |
| [Infographics](gallery/infographic.md) | 38 |
| [Product Thumbnails](gallery/product-thumbnails.md) | 38 |
| [Gig Covers](gallery/gig-covers.md) | 38 |
| [Other Poster Designs](gallery/poster-designs.md) | 20 |

Every image in a gallery links to its live page on [posterlet.com](https://posterlet.com), where you can view it full size,
remix it as a template, or browse the same tags. Click a title to open that poster's full prompt in place.

## Linking to a single poster

Each entry carries an anchor built from its slug, so any one poster can be cited directly:
`gallery/halloween.md#halloween-party-recap-social-poster`.

`data/posters.jsonl` holds the same 250 records as JSON lines — slug, title, ratio, tags, prompt, image
URLs and page URL — if you want to load them programmatically instead of scraping the tables.

## Using these prompts

Copy a spec, swap the `[Subject]` and `[Headline]` blocks, keep the structure. The section headers are the
part that carries the weight — models follow `[Layout]` instructions far more reliably when the frame,
palette and subject are already pinned down by their own sections.

Text rendering (headlines, prices, tags) is the usual failure point: keep quoted copy short, explicitly name
the type style, and state the position twice — once in `[Layout]`, once in `[Headline]`.

## License

Prompt text is licensed [CC BY 4.0](LICENSE) — use it commercially, just credit
[posterlet.com](https://posterlet.com). Example images are SI-generated and remain hosted on posterlet.com; they are shown
here for reference and are not included in the license.
