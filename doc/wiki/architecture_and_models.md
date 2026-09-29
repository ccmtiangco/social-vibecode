# Architecture and Models

This document describes the implemented Django social application. It is a living reference for the models and service behavior in `accounts`, `social`, and `advertising`; update it when those interfaces change.

## Application Layout

- `accounts` owns authentication and the custom user model.
- `social` owns posts, images, follows, the chronological feed, and social actions.
- `advertising` owns campaign and creative management, simulated funding, and impression accounting.
- Django templates and static CSS provide the server-rendered interface. SQLite is configured for local development.

All domain models that refer to a user use the configured `AUTH_USER_MODEL` (`accounts.User`). The initial accounts migration is a dependency of social and advertising migrations, so the custom user exists before those foreign keys are created.

## Users and Roles

`accounts.User` extends Django's `AbstractUser`, retaining Django password hashing, username authentication, active/staff/superuser flags, groups, and permissions. Its `user_type` field has two values:

- `member` is the default for new accounts and can use the social features.
- `ad_manager` is a member account with authority to manage its own campaigns.

`user_type` is a product role, not an admin-site permission. `is_staff` and `is_superuser` retain their Django meanings. Public registration uses `MemberCreationForm`, which does not expose `user_type`; a submitted role value is ignored. The Django admin exposes the role field to superusers, while other staff see it read-only.

Campaign services authorize an active ad-manager owner or an active staff user with the `advertising.change_adcampaign` permission. Merely setting `is_staff` does not grant campaign-management access. Staff with that permission can manage campaigns across owners; an ad manager can manage only their own.

## Social Models

### Posts and images

| Model | Main fields and relationships | Behavior |
| --- | --- | --- |
| `Post` | `author`, optional `body`, `created_at`, optional self-reference `reshared_post`, `is_deleted`, `deleted_at` | Original posts have no `reshared_post`; a reshare is a new activity row. |
| `PostImage` | `post`, `image`, `position`, optional `alt_text`, `created_at` | One post can have ordered image attachments; `(post, position)` is unique. |

`social.services.create_post` is the supported creation boundary. An original must contain text or at least one image. A reshare may contain optional commentary, points to an original post, and cannot attach a copy of the original's images. The original content remains canonical. The model check constraint rejects a direct self-reshare, and model validation rejects resharing another reshare or a deleted original.

Images are stored outside the database through Django's `ImageField`. `MEDIA_ROOT` and `MEDIA_URL` use local storage in development; upload names are generated rather than taken from the user's filename. Server validation accepts JPEG, PNG, and WebP files up to 5 MiB and 40 million pixels. `create_post` validates the complete image set before saving, writes the post and attachments in a database transaction, and cleans up files if the database operation fails. Image file deletion is deferred until the database deletion commits.

Deleting a post with reshares through its model instance changes it into a tombstone: the row and reshare references remain, its body is cleared, its images are removed, and `deleted_at` is set. A post without reshares is physically deleted. The reshare foreign key uses `PROTECT`, preventing a referenced original from being removed by a bulk/cascade operation. Application actions should use instance deletion when tombstoning is intended.

### Follows

`Follow` is a directed relationship from `follower` to `followed`, with a creation timestamp. The database enforces unique `(follower, followed)` pairs and rejects self-follows. Composite indexes support lookups in both directions. Follow and unfollow are authenticated POST actions; they do not mutate state on GET.

## Advertising Models and Budgets

| Model | Purpose | Important fields |
| --- | --- | --- |
| `AdCampaign` | An ad manager's scheduled campaign and budget | `owner`, `status`, `starts_at`, `ends_at`, `currency_code`, `funded_total_minor`, `spent_total_minor`, `impression_cost_minor` |
| `AdCreative` | A deliverable variation belonging to a campaign | `headline`, `body`, optional validated `image`, `destination_url`, `is_active`, `is_approved` |
| `AdPurchase` | A simulated funding ledger record | `campaign`, `purchaser`, `amount_minor`, `payment_method`, `status`, unique reference |
| `AdImpression` | An idempotently charged delivery record | `campaign`, `creative`, `viewer`, `idempotency_key`, `charged_amount_minor`, `occurred_at` |

All monetary values use integer minor currency units, not floats. Funded/spent balances may be zero; purchase amounts, impression charges, and impression costs must be positive. Campaign currency defaults to USD. Database constraints enforce valid campaign date ranges, nonnegative budget fields, spend not exceeding funded balance, positive impression costs and ledger amounts, and unique `(viewer, idempotency_key)` impressions.

Campaign states are `draft`, `active`, `paused`, and `ended`. The status service permits draft to active/paused/ended, active to paused/ended, and paused to active/ended; ended is terminal. Activating a campaign requires enough remaining funds for at least one impression and an end time in the future. Funding a draft through a simulated purchase activates it; funding a paused campaign does not resume it.

`purchase_campaign(actor, campaign_id, amount_minor)` accepts whole minor units from 1 through 10,000,000. It checks ownership/permission and campaign eligibility, creates an `AdPurchase` marked `simulated`, and increments `funded_total_minor` atomically. It collects no payment credentials and moves no real money. `funded_total_minor` is an aggregate backed by the purchase ledger.

`charge_impression(viewer, creative_id, idempotency_key)` is the separate delivery-accounting boundary. It only charges an authenticated active viewer when the campaign is active and within its date window, the creative is active and approved, and enough budget remains. A repeated key for the same viewer and creative returns the existing impression without charging again; reusing the key for a different creative is rejected. A conditional update protects the budget invariant in addition to transaction and row-lock handling. Django admin shows purchase and impression ledgers read-only.

## Feed Generation

`social.feed.get_feed_page(viewer, cursor=None, page_size=None)` requires an active authenticated user. It queries the viewer's own posts plus posts by followed users, excludes tombstoned activities, and sorts newest first by `(created_at, id)`. The follow relationship is used as a database subquery. The query loads authors and reshared originals with `select_related`, and images with `prefetch_related`.

Pagination is keyset-based, not offset-based. Each signed cursor is bound to its viewer and contains the last organic post's timestamp and ID. The service fetches at most one page plus one lookahead row; inserted ads do not move the organic cursor. Cursors expire after 30 days. The default page size is 20 and the service caps requested page sizes at 100.

Ad insertion is a separate bounded candidate query. A creative is eligible only when it is active and approved, its campaign is active and inside its date window, and remaining funds cover one impression. By default, the service adds one sponsored entry after each eight organic activities, up to two ads per page. The interval and page ad cap are settings (`FEED_AD_INTERVAL` and `FEED_MAX_ADS_PER_PAGE`). Sponsored entries carry an explicit `Sponsored` label. The signed cursor also carries a bounded recent campaign history to limit repeat exposure across pages; campaigns seen on the page are excluded on subsequent pages.

Selecting an ad candidate for the feed does not itself charge an impression. The rendered/viewed event must call `charge_impression`; this keeps candidate selection non-billable and lets the service recheck campaign status and budget at charge time.

## Routes and Operations

- `/accounts/register/`, `/accounts/login/`, and POST-only `/accounts/logout/` provide authentication.
- `/` is the authenticated chronological feed; `/users/<username>/` is a public profile.
- `/posts/new/`, `/users/<username>/follow/`, `/users/<username>/unfollow/`, and `/posts/<id>/reshare/` perform authenticated POST social actions (the post form also has a GET page).
- `/ads/` is the campaign dashboard. Campaign, creative, status, and simulated funding writes are view-authorized and CSRF-protected.

Useful local verification commands:

```sh
venv/bin/python manage.py test
venv/bin/python manage.py check
venv/bin/python manage.py migrate --check
venv/bin/python manage.py makemigrations --check --dry-run
```

## Current Scope Limits

- Media uses local `MEDIA_ROOT` in development. Production needs durable object storage and appropriate delivery configuration.
- Purchases are simulated; there is no payment gateway, card handling, refund flow, or provider webhook integration.
- Impression charges are recorded by the service but are not triggered automatically by rendering a feed response; a viewable-impression integration remains future work.
- SQLite is the local database. Its row-lock behavior is insufficient for production concurrent billing; use PostgreSQL for that workload.
- Feed generation is fan-out-on-read and currently assumes public social posts. Private accounts, blocks, advanced ad targeting, and high-volume feed fan-out are not implemented.
