# Architecture and Data Models

## Scope and Feasibility

The requested MVP is feasible with Django's ORM, templates, and a relational database. The current repository is a fresh Django 6.1 project with SQLite and only the generated `core` project; it does not yet have application models or migrations. The highest-impact early decision is to define the custom user model before the first project migration. Changing `AUTH_USER_MODEL` after other models reference Django's default user is a costly migration.

Use a small number of relational models and serve the feed with indexed, paginated ORM queries. SQLite is adequate for local development and a small demonstration, but PostgreSQL is the recommended deployment database once there are concurrent feed requests, ad spend accounting, or multiple application workers. A real payment integration, large-scale feed fan-out, and sophisticated ad targeting are outside the MVP and should not be prerequisites for demonstrating the product.

## User Management

### Proposed approach

Create one custom user model by subclassing `AbstractUser`, and set `AUTH_USER_MODEL` to it before running the initial migrations. Add a `user_type` field with values such as `member` and `ad_manager`; default new public registrations to `member`. Keep the built-in `is_active`, `is_staff`, `is_superuser`, password, session, and permission behavior. Use Django groups and permissions for authorization checks, with the role field expressing the product-level account type rather than acting as the only security boundary.

Both account types remain rows in the same user table. Posts, follows, and campaign ownership can therefore use ordinary foreign keys to `settings.AUTH_USER_MODEL`. Restrict campaign creation and management in server-side views/services and querysets; hiding links in HTML is not access control. Decide how ad-manager accounts are granted (for example, staff approval or a separate onboarding path) rather than allowing a client-supplied role during ordinary registration.

### Tradeoffs

- A single custom user model avoids duplicated authentication, login, password reset, and session logic. It also makes the first migration more consequential, which is why it should be created before other app migrations.
- Separate `Member` and `AdManager` subclasses or separate authentication tables would complicate permissions and relationships without providing useful isolation for this scope.
- A single `user_type` assumes an account has one primary type. If people later need to use the same account both socially and as an advertiser, keep the one user identity and represent advertiser access through a group or an organization membership rather than creating a second login.
- Django's `is_staff` means admin-site access, not "ad manager"; do not conflate the two.

## Core Schema

All user references below point to the configured custom user model. Public visibility is assumed for the MVP; private accounts, blocks, and per-post audience rules would add feed filtering and should be treated as explicit product decisions.

### Posts and images

Use a `Post` model with an author foreign key, optional text body, creation timestamp, and an optional self-reference `reshared_post` (null for an original post). A reshare is a new `Post` activity authored by the person sharing it and pointing to the original. The body can hold optional quote commentary. Rendering a reshare displays the referenced original without copying its text or images, so edits and moderation do not leave stale duplicated content.

Represent uploaded images with a `PostImage` model related to `Post`, containing an `ImageField`, ordering position, optional alt text, and creation metadata. A related image table supports multiple images per post and can later support reordering or removal without changing the post schema. If product scope is firmly limited to one image per post, a single nullable `ImageField` on `Post` is a smaller alternative; the related table is the recommended choice if galleries are plausible.

The application should validate that an original post has text or at least one image, and that a reshare points to an existing original. Because images are related rows, the "text or image" rule cannot be fully enforced with a simple database check constraint; enforce it in a post-creation service/form within a transaction. Prevent a post from resharing itself, and preserve or tombstone originals that have reshares rather than silently turning those reshares into empty posts. A database check plus application validation is appropriate for the self-reference rule.

`ImageField` stores a path, not the image bytes in the relational database. Use local media storage during development and a durable object-storage backend (with CDN delivery as needed) in production. Validate image type and size on the server, generate non-user-controlled storage names, and do not trust the filename or browser-provided content type. Configure `MEDIA_ROOT`/`MEDIA_URL` for development; Django's development media serving is not a production storage strategy. Deleting a database row does not necessarily delete its external file, so define cleanup behavior.

### Follows

Use a directed `Follow` model with `follower`, `followed`, and `created_at`. Add a unique constraint on `(follower, followed)` to prevent duplicate follows and a check constraint preventing a user from following themself. Add indexes that support both "who does this user follow?" and "who follows this user?" lookups. These constraints make follow/unfollow idempotent and keep the relationship semantics explicit.

### Sharing and reposting

Model a repost as a `Post` row whose `reshared_post` points to the original, rather than as a separate feed-event table. This keeps originals and reshare actions in one chronologically ordered feed query. A separate `Repost` table is more normalized and can make reshare-specific data clearer, but requires merging and paginating two event streams for every feed request. The single-table activity representation is a better MVP tradeoff. Retain the original post's author/content as the canonical source and show the resharer's identity separately. A uniqueness rule on `(author, reshared_post)` is optional; add it only if the product disallows sharing the same post more than once.

Suggested indexes include `(author, -created_at, -id)` on `Post` for the feed and an index on `reshared_post` for locating reshares. Use stable timestamp-plus-primary-key ordering to handle posts created at the same time.

## Ad System

### Proposed schema

- `AdCampaign`: owner/ad-manager foreign key, name, status (`draft`, `active`, `paused`, `ended`), start and end times, a funded amount, a spent amount, and creation/update timestamps. Campaign state and time window both determine whether an ad is eligible.
- `AdCreative`: campaign foreign key, text/headline, optional image path, destination URL, and active/approved state. Keeping creative separate allows a campaign to contain more than one ad variation without duplicating its budget and owner.
- `AdPurchase`: campaign foreign key, purchaser, integer amount in minor currency units (for example cents), status, simulated/real payment method marker, and timestamp/reference. This is an append-only record of funding events.
- `AdImpression`: campaign and creative foreign keys, viewer, timestamp, and charged amount in minor units. This records served impressions and makes spending auditable. Add an idempotency key or a suitable uniqueness/frequency rule if impressions are recorded from browser events that may be retried.

Use integer minor currency units rather than floating point or `Decimal` arithmetic for campaign balances. On a simulated purchase, create a successful `AdPurchase` and increase the campaign's funded total; this is a ledger entry, not a payment. For a simple demo, a "Purchase" action can grant the campaign a fixed or user-selected test budget and mark the campaign funded/active. Clearly label this as simulated. Do not collect card details or imply that money moved. A payment gateway can later replace the simulated purchase path while keeping campaign and purchase records.

Treat funded and spent totals as cached aggregates backed by the purchase and impression records, not as the only source of truth. Update the ledger and aggregate in one database transaction. When reserving or charging an impression, check that the campaign remains in its date window and has budget; use a row lock/atomic conditional update to avoid concurrent requests overspending. SQLite has limited row-level concurrency behavior, so PostgreSQL is preferred if this becomes a real billing path. In the MVP, impression events can be charged at a fixed simulated rate. Real billing requires decisions about CPM/CPC pricing, viewability, fraud, refunds, and payment-provider webhooks.

Campaign and creative management must be restricted to the owning ad manager (and authorized staff). Only active, funded campaigns with active creatives should be considered for delivery. Ads should be visibly labelled "Sponsored"; ad creative should not masquerade as an ordinary user post.

## Feed Algorithm and Performance

### MVP read path

Use a fan-out-on-read chronological feed: look up the viewer's followed user IDs, include the viewer's own posts, then fetch the newest matching `Post` activities ordered by `created_at` descending and `id` descending. Because reshares are also `Post` rows, the same query naturally includes posts and reshare events. Add indexes on `Follow(follower, followed)` and `Post(author, created_at, id)` to support this access pattern. Load authors and reshared originals with `select_related`, and post images with `prefetch_related`, to avoid per-item database queries.

Use keyset/cursor pagination rather than large SQL offsets. The cursor contains the last organic activity's `(created_at, id)` pair, and the next query filters for rows older than that pair. This avoids scanning increasingly large offsets and gives deterministic ordering when timestamps tie. Fetch only one page plus a small lookahead, not an unbounded timeline.

### Ad insertion

Fetch organic activities independently from ads so ad eligibility or creative joins do not slow down the main feed query. For each page, fetch a bounded set of eligible campaigns/creatives whose state, start/end times, and remaining funded budget permit delivery. Insert a sponsored item after a fixed number of organic items (for example, after every eight); make the interval configurable and cap the number of ads per page. For a small campaign set, a database query with indexes on campaign state/time and a bounded candidate list is sufficient. Avoid sorting every campaign randomly or checking campaigns one by one in application code.

Keyset progress should be based on the last organic activity, not the mixed list position, so an ad neither displaces nor skips a post. Keep placement deterministic for the page/cursor where practical, and avoid repeating the same creative within one page. Prevent excessive repeats across pages with a viewer/campaign frequency cap or a small set of already-served IDs in the signed/session cursor. Record an impression only when the ad is actually rendered/viewed according to the chosen MVP rule, not merely because it was considered as a candidate. This separates feed retrieval from billing and makes retry behavior explicit.

### Scaling tradeoffs

- Fan-out-on-read is simple, preserves a fresh chronological feed, and is a good fit for an MVP with modest follow graphs. Its query gets more expensive for users following very many accounts.
- If read latency becomes a problem, add an asynchronously maintained per-user timeline/inbox for ordinary accounts (fan-out-on-write), while retaining read-time merging for very high-follower accounts to avoid writing every post to millions of timelines. This is a later optimization, not a starting requirement.
- Cache a short-lived, bounded eligible-ad candidate set if campaign volume grows; recheck state and budget before recording a charged impression. Keep targeting and ranking simple until there is enough traffic and consented data to justify them.
- PostgreSQL, appropriate indexes, bounded page sizes, and avoiding N+1 queries will matter before adding Redis, a search engine, or a dedicated feed service.

## Recommended MVP Decisions

1. Create the `AbstractUser`-based custom user and configure `AUTH_USER_MODEL` before the first migration.
2. Use one user table with a member/ad-manager account type and Django permissions for access control.
3. Store originals and reshare activities in `Post`, with a self-reference for reshares; store images as related `PostImage` rows in media storage.
4. Use a directed, uniquely constrained `Follow` relationship.
5. Represent campaigns, creatives, simulated purchases, and impressions separately; track budgets in integer minor units and retain the ledger.
6. Start with a paginated, fan-out-on-read chronological feed and insert bounded sponsored slots after querying organic activities.
7. Keep SQLite for local development, but move to PostgreSQL before relying on concurrent budget accounting or production traffic.

These choices are feasible with the current Django project and keep the first implementation understandable. They also preserve clear upgrade paths for real payments, richer account memberships, multi-image posts, privacy controls, and higher-volume feed delivery without requiring those systems in the first release.
