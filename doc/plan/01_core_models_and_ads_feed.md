# Core Models and Ads Feed Implementation Plan

This plan turns the decisions in [the architecture study](../study/01_architecture_and_models.md) into a sequential implementation checklist. Complete each phase in order; later model migrations depend on the custom user model established in Phase 1.

## Execution Guardrails

- Execute this plan on a separate Git branch from `main`, as required by `agents.md`.
- Keep this planning step documentation-only. Do not create implementation files until the plan is approved and execution begins.
- Commit each coherent phase with one of the suggested conventional commit messages below. Run the phase's focused tests before committing.
- Keep SQLite for local development. Treat PostgreSQL deployment, a real payment provider, and high-volume feed infrastructure as out of scope for this MVP.

## Phase 1: App Configuration and Custom User Setup

**Goal:** Establish the project's permanent user model and apply its baseline migration before creating any social or advertising model migrations.

- [x] Create an `accounts` Django app dedicated to authentication and user identity.
- [x] Add `accounts` to `INSTALLED_APPS` and configure `AUTH_USER_MODEL = "accounts.User"` in project settings before creating any non-auth model migrations.
- [x] Implement `User` by subclassing `AbstractUser`; add a `user_type` field with `member` and `ad_manager` choices and a safe default of `member`.
- [x] Preserve Django's password, active, staff, superuser, session, and permission behavior. Do not use `is_staff` to represent an ad-manager account.
- [x] Ensure ordinary registration cannot submit or elevate `user_type`; reserve ad-manager assignment for an authorized onboarding or staff-controlled path.
- [x] Create and inspect the `accounts` initial migration and its dependency on Django auth migrations.
- [x] Apply the baseline migration, including Django's built-in migrations and the new custom user table, before generating migrations for `social` or `advertising`.
- [x] Create a superuser and verify that login, password handling, and admin access work with the custom user model.
- [x] Add focused tests for the default member type, explicit authorized ad-manager assignment, and preservation of staff/superuser semantics.

**Suggested commit:** `feat(accounts): add custom user model`

## Phase 2: Core Social Models and Media Handling

**Goal:** Implement social data on top of the migrated custom user, with safe image uploads and usable admin/seed controls.

- [x] Create and install a `social` app. Reference users through `settings.AUTH_USER_MODEL` rather than importing Django's default user model.
- [x] Implement `Post` with author, optional body, creation timestamp, and nullable self-reference `reshared_post`; a non-null reference represents a reshare activity, and body text on that activity is optional quote commentary.
- [x] Implement `PostImage` with a foreign key to `Post`, `ImageField`, ordering, optional alt text, and upload paths that do not trust user-supplied filenames.
- [x] Implement `Follow` with follower, followed, and creation timestamp; enforce unique `(follower, followed)` pairs and prohibit self-following.
- [x] Add feed and relationship indexes: posts by author and descending creation time/ID, reshares by original post, and follows in both lookup directions.
- [x] Validate that an original post has text or at least one image, that a reshare references an original, and that a post cannot reshare itself. Perform post-plus-image creation atomically so failed image validation does not leave partial posts.
- [x] Decide and implement original-post deletion behavior that preserves/tombstones originals with reshares instead of leaving blank reshares.
- [x] Add `Pillow` for image validation and record it in the project's dependency manifest; add a manifest if none exists when implementation begins.
- [x] Configure local `MEDIA_ROOT` and `MEDIA_URL` for development only. Set server-side file-size/type validation and document that production requires durable object storage rather than Django development media serving.
- [x] Define file cleanup behavior when posts or images are removed; do not assume deleting a database row removes a stored file.
- [x] Create and inspect the `social` migrations only after the Phase 1 baseline migration is applied.
- [x] Register users, posts, images, and follows in Django admin with useful list filters/search and safe handling of user/role fields.
- [x] Add an idempotent development seed command for sample members, follows, posts/images where practical, and reshares; make it safe to rerun and avoid hard-coded production credentials.
- [x] Add tests for relationship constraints, post validation, multi-image uploads, invalid/oversize files, reshare references, and deletion/tombstone behavior.

**Suggested commits:** `feat(social): add posts follows and media handling`; `chore(social): add admin and development seed data`

## Phase 3: Advertising Models and Simulation Services

**Goal:** Add campaign ownership, creatives, simulated funding, and auditable impression accounting without integrating real payments.

- [x] Create and install an `advertising` app. Use the custom user model for campaign owners, purchasers, and impression viewers.
- [x] Implement `AdCampaign` with owner, name, status, start/end times, funded and spent totals, and timestamps. Define valid status transitions for draft, active, paused, and ended campaigns.
- [x] Implement `AdCreative` with campaign, copy/headline, optional image, destination URL, and active/approval state. Keep creatives separate so a campaign can contain more than one ad variation.
- [x] Implement append-only `AdPurchase` funding records and `AdImpression` records with campaign, creative, viewer, timestamp, and charged amount. Store all monetary values as integer minor currency units.
- [x] Add database constraints and indexes for campaign date/state lookups, ownership queries, and campaign-to-creative/purchase/impression lookups.
- [x] Implement a server-side simulated-purchase service that checks the authenticated user's campaign ownership and eligibility, validates the amount, then creates the purchase record and updates funded balance atomically.
- [x] Ensure simulated purchase does not collect payment credentials or claim that real money moved. The admin ledger labels purchases as simulated; Phase 5 adds the user-facing dashboard label.
- [x] Implement impression charging with an atomic budget check/update and a recorded charge; make repeated client submissions idempotent using an event key or an explicit duplicate-detection rule.
- [x] Use a transaction and row locking/conditional updates around balance changes. Document that SQLite has limited row-level locking and that real concurrent billing should use PostgreSQL.
- [x] Restrict campaign and creative changes to the owning ad manager or authorized staff; reject member access in the service/view layer, not only in templates.
- [x] Create and inspect the advertising migration after Phase 1, then verify model/admin behavior in Django admin.
- [x] Add tests for owner isolation, member denial, invalid campaign dates/status, atomic simulated funding, insufficient funds, and duplicate impression retries.

**Suggested commit:** `feat(advertising): add campaigns and simulated funding`

## Phase 4: Feed Generation and Interleaving Logic

**Goal:** Serve a bounded chronological feed and interleave eligible ads without changing organic pagination progress.

- [ ] Implement a feed service that gathers the viewer's followed user IDs, includes the viewer's own posts, and queries matching `Post` activities in descending `(created_at, id)` order.
- [ ] Use keyset pagination with a cursor based on the last organic `(created_at, id)` pair; do not use large offsets or let inserted ads advance the organic cursor.
- [ ] Fetch a page plus a small lookahead only. Load authors and reshared originals with `select_related` and images with `prefetch_related` to avoid N+1 queries.
- [ ] Add focused query/index validation for the feed's author/time ordering and the follow lookup path.
- [ ] Implement a separate, bounded ad-candidate query for active, approved creatives in active, funded campaigns whose date window includes the current time.
- [ ] Interleave sponsored items at a configurable fixed interval (initial target: one ad after every eight organic activities) and enforce a maximum ad count per page.
- [ ] Keep organic pagination deterministic if campaign eligibility changes between requests; use a signed cursor or equivalent page state where needed, and do not skip or duplicate organic posts because an ad was inserted.
- [ ] Avoid repeating the same creative within a page and apply an MVP viewer/campaign frequency cap across pages using recent impression state or cursor/session state.
- [ ] Clearly mark each inserted item as `Sponsored`; record an impression only when the chosen rendered/viewed event occurs, not when merely selecting a candidate.
- [ ] Recheck campaign status and remaining funds before charging an impression so a stale candidate cannot spend a paused or exhausted campaign.
- [ ] Add tests for chronological ordering and timestamp ties, own-post inclusion, followed-author filtering, reshare activity ordering, cursor continuation, exact ad interval/cap, no-eligible-ad behavior, and frequency limits.

**Suggested commit:** `feat(feed): add chronological feed with sponsored placements`

## Phase 5: Frontend Templates and UI

**Goal:** Expose the social and campaign workflows through accessible, server-rendered HTML/CSS templates.

- [ ] Add shared base/layout and responsive CSS for navigation, forms, post cards, image galleries, and sponsored labels.
- [ ] Add registration and login/logout templates using Django authentication. Public registration must create members only; ad-manager role assignment stays on an authorized path.
- [ ] Add user profile pages showing profile identity and the user's original posts and reshare activities.
- [ ] Add post creation with text and multiple image upload support, correct `multipart/form-data` encoding, validation feedback, and CSRF protection.
- [ ] Add follow/unfollow controls implemented as authenticated POST actions; show follow state and useful success/error messages.
- [ ] Add reshare and optional quote-reshare POST actions that create a new activity referencing the original rather than copying its content.
- [ ] Add the unified feed template for organic posts, reshare attribution, attached images, pagination, and visibly labelled sponsored creative cards.
- [ ] Add an ad-manager dashboard for campaign creation/editing, creative management, dates/status, remaining budget, purchase history, and impression/spend summaries.
- [ ] Add a simulated purchase action that is clearly labelled as a demo and displays the credited amount and resulting available budget.
- [ ] Enforce authorization and ownership in views/services for every write action; do not rely on hiding controls in templates.
- [ ] Add template/view tests for logged-out redirects, CSRF-safe POST routes, member/ad-manager access boundaries, and empty/error states.
- [ ] Manually check keyboard navigation, labels/alt text, responsive layout at narrow and wide viewport sizes, and visible sponsored disclosure.

**Suggested commit:** `feat(web): add social and campaign templates`

## Phase 6: Verification and Testing

**Goal:** Verify the combined system and document the MVP's known limitations before rendezvous.

- [ ] Run the complete automated test suite and resolve failures before considering the implementation branch ready.
- [ ] Run Django system checks and confirm there are no unapplied migrations or accidental model changes missing migrations.
- [ ] Verify custom-user migration ordering from a clean local database: the custom user is established before social and advertising foreign keys are applied.
- [ ] Test permissions end to end: member registration cannot self-assign ad-manager status; members cannot create/manage campaigns; ad managers cannot access another owner's campaign; staff can perform intended administrative actions.
- [ ] Test uploads end to end: valid image acceptance, invalid/non-image rejection, configured size limits, multiple images, correct rendering, and cleanup/tombstone behavior.
- [ ] Test social actions end to end: follow/unfollow idempotence, self-follow rejection, post validation, reshare attribution, original-content rendering, and original deletion behavior.
- [ ] Test feed behavior end to end: only own/followed activity appears, order remains chronological, cursor pages neither skip nor duplicate organic items, ads appear at the configured interval/cap, and exhausted/paused/out-of-window campaigns are not served.
- [ ] Test simulated ad accounting end to end: purchase history and balance are correct, impression charging stops at budget exhaustion, duplicate events do not double-charge, and every served creative is labelled sponsored.
- [ ] Review query counts on a representative feed page to catch N+1 regressions and confirm page/candidate limits are bounded.
- [ ] Perform a manual browser walkthrough covering registration/login, profile, post/image creation, follow/unfollow, reshare, feed pagination, campaign setup, simulated purchase, and sponsored placement.
- [ ] Record remaining scope limitations: local media storage is development-only, purchases are simulated, and SQLite is not the target for concurrent production ad accounting.

**Suggested commit:** `test: cover social permissions and ad feed behavior`

## Completion Criteria

- [ ] All six phases are complete and their focused tests pass.
- [ ] A clean local database can be migrated and the main member and ad-manager journeys can be completed manually.
- [ ] No real payment processing, production media credentials, or secrets were introduced as part of the MVP.
- [ ] The implementation branch is ready for the workflow's rendezvous step; update living documentation during the later sync-docs step.
