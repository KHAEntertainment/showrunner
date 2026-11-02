# Showrunner badges

Add a **Built with Showrunner** badge to your project's README. Every badge is
served from `svg.khaentertainment.com`, is animated, and links back to
[Showrunner](https://github.com/KHAEntertainment/showrunner).

## Quick copy

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=orbit)](https://svg.khaentertainment.com/go)
```

There is no placeholder to fill in. The badge and its link work straight away:
the link redirects to the Showrunner repository. Adding the badge does not by
itself add a project to the adoption count.

Removing the badge is just deleting the line. Nothing else changes.

## Variants

### flat · midnight · orbit

![flat · midnight · orbit](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=orbit)](https://svg.khaentertainment.com/go)
```

### flat · midnight · sweep

![flat · midnight · sweep](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=sweep)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=sweep)](https://svg.khaentertainment.com/go)
```

### flat · midnight · both

![flat · midnight · both](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=both)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=both)](https://svg.khaentertainment.com/go)
```

### flat · midnight · static

![flat · midnight · static](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=none)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=midnight&anim=none)](https://svg.khaentertainment.com/go)
```

### flat · onyx · orbit

![flat · onyx · orbit](https://svg.khaentertainment.com/badge.svg?theme=onyx&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=onyx&anim=orbit)](https://svg.khaentertainment.com/go)
```

### flat · classic · orbit

![flat · classic · orbit](https://svg.khaentertainment.com/badge.svg?theme=classic&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?theme=classic&anim=orbit)](https://svg.khaentertainment.com/go)
```

### for-the-badge · orbit

![for-the-badge · orbit](https://svg.khaentertainment.com/badge.svg?style=for-the-badge&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?style=for-the-badge&anim=orbit)](https://svg.khaentertainment.com/go)
```

### for-the-badge · both

![for-the-badge · both](https://svg.khaentertainment.com/badge.svg?style=for-the-badge&anim=both)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?style=for-the-badge&anim=both)](https://svg.khaentertainment.com/go)
```

### flat-square · orbit

![flat-square · orbit](https://svg.khaentertainment.com/badge.svg?style=flat-square&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?style=flat-square&anim=orbit)](https://svg.khaentertainment.com/go)
```

### no logo

![no logo](https://svg.khaentertainment.com/badge.svg?logo=none&anim=orbit)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?logo=none&anim=orbit)](https://svg.khaentertainment.com/go)
```

### no gold rim

![no gold rim](https://svg.khaentertainment.com/badge.svg?gold=0)

```markdown
[![Built with Showrunner](https://svg.khaentertainment.com/badge.svg?gold=0)](https://svg.khaentertainment.com/go)
```

## Parameters

| Param | Values | Default |
| --- | --- | --- |
| `style` | `flat`, `flat-square`, `for-the-badge` | `flat` |
| `theme` | `midnight`, `onyx`, `classic` | `midnight` |
| `anim` | `orbit`, `sweep`, `both`, `none` | `orbit` |
| `logo` | `clapperboard`, `dot`, `none` | `clapperboard` |
| `gold` | `0` removes the gold rim | on |
| `label`, `message` | any text | Built with / Showrunner |
| `color`, `labelColor`, `textColor`, `labelTextColor`, `logoColor` | any CSS colour | from `theme` |
| `project` | `owner/repo` | read from the click |

## Notes

Badges animate on GitHub: the Camo image proxy passes SVG animation through
untouched. Readers who set `prefers-reduced-motion` get a static gold rim
instead of a moving one.

How many badges a README should carry is your call. These sit well either
directly under a banner or in a row with your CI and license badges.
