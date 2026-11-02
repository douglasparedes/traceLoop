# UI/UX Audit — TraceLoop (November 2026)

Audit of the pre-redesign application, and what was changed. Verified
against the running app at desktop (1440), tablet (768), and mobile (390).

## A. Findings

### Navigation
| Problem | Screen | Why it harms | Change | Priority |
|---|---|---|---|---|
| 9 permanent desktop destinations (Workbench, Procedures, Capture, Review, Guided job, Activity, History, Manuals, Settings) | All | No hierarchy; Guided job is a mode, not a place; Activity/History duplicate each other | 4 primary (Workbench, Procedures, Tutorials, Activity) + secondary group (Review, Manuals, Settings) | P0 |
| Mobile bottom nav had 5 items incl. Settings; tablet had no intentional layout | All | 9 desktop buttons wrapped awkwardly at 768 | 4-item bottom nav; Settings moved to header profile menu | P0 |
| Review competed with primary destinations | All | Approvals felt like just another tab | Pending reviews surface on Workbench + Activity; Review is secondary but badged | P1 |
| No breadcrumb/back on detail/editor screens | Detail, Studio | Users get lost in deep views | Back-to-library buttons + Studio header with back action | P1 |

### Capture
| Problem | Screen | Why it harms | Change | Priority |
|---|---|---|---|---|
| Three-mode switcher (Quick capture / Live / Record a tutorial) | Capture | User must choose a paradigm before understanding the product | Single workflow: Record a tutorial | P0 |
| Hardcoded demo title, equipment, transcript, segmentation prompt in new-user forms | Capture | Looks like real data; users must delete placeholder text | Empty fields + helpful placeholders | P0 |
| Transcript-correction callback fed the deleted Quick Capture flow | Tutorial transcript | Dead-end cross-link | Removed; correction lives in Tutorial Studio | P0 |
| Recording UI buried under mode switch | Capture | Extra taps to the only action that matters | Persistent "Record a tutorial" card atop Tutorials | P1 |

### Tutorial library & editing gaps
| Problem | Screen | Why it harms | Change | Priority |
|---|---|---|---|---|
| Library only visible inside the recording state; vanished when a tutorial opened | TutorialMode | No persistent collection; can't compare or return | Persistent library under Tutorials, independent of recording | P0 |
| Title/metadata not editable after upload | — | Typos permanent | Overview editor (title, equipment, task, notes) | P0 |
| Transcript corrections impossible; original vs corrected undistinguished | — | Errors frozen into guides | Transcript + timed-segment editor; original preserved | P0 |
| Steps not editable as structured data | — | Only Markdown string of truth | Canonical step CRUD + reorder + tools/evidence links | P0 |
| Guide regeneration was all-or-nothing with no version compare from Studio | — | Can't audit what changed | Snapshot history + view/compare in Guide tab | P1 |
| Video scenes not editable; only latest MP4 kept via API | — | No iteration on video guides | Scene plan editor + versioned renders + per-version download | P0 |
| Visual editing detached from steps | — | Unclear which step uses a visual | Visuals tab with step→source→asset chain; accept/reject preserved | P1 |
| Approved revisions could be silently affected by regenerations after approval | API | Data-integrity risk | Regen dedup now skips locked drafts; content edits fork new revisions; approved rows never mutated (tested) | P0 |

### Visual design
| Problem | Screen | Why it harms | Change | Priority |
|---|---|---|---|---|
| Green-tinted surfaces everywhere; cards inside cards; decorative uppercase microcopy | All | SaaS-dashboard feel, weak hierarchy | Neutral near-white surfaces; green reserved for actions/selection; tighter radii/shadows | P1 |
| Page headings 23px desktop; weak type scale | All | Flat hierarchy | 28px page / 18–21 section / 16–19 execution text | P2 |
| Every tutorial an oversized dashboard card | Library | Poor density | Compact row list (desktop) / compact cards (mobile) | P1 |
| Inline styles per screen; no studio component system | All | Inconsistent spacing | Shared studio/tut-list/scene-list classes | P2 |
| Status shown by color alone in places | Various | Accessibility | Badges keep glyph + uppercase label + tint | P1 |

### Responsive
| Problem | Screen | Why it harms | Change | Priority |
|---|---|---|---|---|
| 768px: 9 nav buttons wrapped; modal/drawer cramped | Nav, job | Broken layout | 4-tab bottom nav ≤899px; compact sidebar ≥1100px | P0 |
| Long transcripts / many scenes overflowed | Guide, video | Horizontal scroll | Wrapping titles, scrollable scene lists, stacked studio grid on mobile | P1 |

## B. Verification (post-change, real browser + API)

- 390 / 768 / 1440: Tutorials view renders, no Quick/Live controls, no horizontal overflow, 4 bottom tabs on mobile, zero page errors.
- API journeys (simulated pipeline, real ffmpeg + real Remotion renders): new tutorial → edit title/transcript/steps/reorder → reload persists; format change → immutable snapshots; scene edit → new MP4 version, both MP4s served; approve → edit → fork (approved row byte-identical).
- Suites: backend 65 passed + 1 skipped; frontend 58 passed; `tsc -b` clean; production build clean.
