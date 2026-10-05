_Last updated: 2026-10-05 — T7: payment provider is stored at startup; no request calls charge._

# Data flow

Startup writes the seed into SQLite and keeps a session factory. `create_app` also stores one `FakeNotifier` on `app.state.notifier` and one `FakePaymentProvider` on `app.state.payment_provider`. No request reads the payment provider. After that, HTTP data moves on the health check, the user list, `GET /me`, the catalog routes, `POST /orders/preview`, `POST /orders`, `GET /orders/{order_id}`, `GET /patient/orders`, and `POST /orders/{order_id}/cancel`. Catalog reads return product JSON. A provider price update validates one line, then writes that provider's `provider_products` row. An order preview reads `provider_products` and `products.unit_cogs_cents`, validates the resolved lines, and returns an `OrderSplit`. It does not write. Create copies that snapshot onto `orders` and `order_lines`, commits, then calls `order_created`. Reads and cancel return stored order columns. Line totals use `line_amounts` on the stored line. The frontend renders a static heading and does not send or receive API data.

```mermaid
flowchart LR
  configUrl["app.config.database_url"] -->|"default sqlite:///./cerbo.db"| lifespan["lifespan"]
  lifespan -->|"create_all"| sqliteFile["SQLite cerbo.db"]
  lifespan -->|"seed then commit"| sqliteFile
  lifespan --> sessionFactory["session_factory"]
  sessionFactory --> getSession["get_session"]
  getSession -->|"Session"| sqliteFile
  buildNotifier["build_notifier"] -->|"one FakeNotifier"| fakeNotifier["app.state.notifier"]
  buildPayment["build_payment_provider"] -->|"one FakePaymentProvider"| paymentState["app.state.payment_provider"]

  httpClient["HTTP client"] -->|"GET /health"| healthFn["health()"]
  healthFn -->|"{status: ok}"| httpClient

  httpClient -->|"GET /users"| listUsers["list_users"]
  listUsers --> getSession
  listUsers -->|"user list JSON"| httpClient

  httpClient -->|"GET /me, X-User-Id"| meRoute["me"]
  meRoute --> currentUser["current_user"]
  currentUser --> getSession
  currentUser -->|"User"| meRoute
  meRoute -->|"200 user JSON"| httpClient
  currentUser -->|"APIError"| apiError["APIError handler"]
  apiError -->|"error JSON"| httpClient

  httpClient -->|"GET /products, X-User-Id"| getProducts["get_products"]
  httpClient -->|"GET /provider/products, X-User-Id"| getProviderProducts["get_provider_products"]
  httpClient -->|"PUT JSON body"| putProviderProduct["put_provider_product"]
  getProducts --> requireRole["require_role"]
  getProviderProducts --> requireRole
  putProviderProduct --> requireRole
  requireRole --> currentUser
  requireRole -->|"403 APIError"| apiError
  getProducts --> catalogSvc["services/catalog"]
  getProviderProducts --> catalogSvc
  putProviderProduct --> catalogSvc
  catalogSvc --> getSession
  catalogSvc -->|"200 product JSON"| httpClient
  catalogSvc -->|"one line, qty 1"| validateOrder["validate_order"]
  validateOrder -->|"PricingError"| pricingHandler["PricingError handler"]
  pricingHandler -->|"422 error JSON"| httpClient
  catalogSvc -->|"upsert provider_products, commit"| sqliteFile
  putProviderProduct -->|"404 APIError"| apiError
  putProviderProduct -->|"invalid body or path"| validationHandler["RequestValidationError handler"]
  validationHandler -->|"422 VALIDATION_ERROR"| httpClient

  httpClient -->|"POST /orders/preview, X-User-Id"| postOrderPreview["post_order_preview"]
  postOrderPreview --> requireRole
  postOrderPreview --> ordersSvc["services/orders"]
  ordersSvc --> getSession
  ordersSvc -->|"read provider_products and unit_cogs_cents"| sqliteFile
  ordersSvc -->|"resolved lines, FEE_BPS_DEFAULT"| validateOrder
  ordersSvc -->|"PricingError"| pricingHandler
  postOrderPreview -->|"422 PRODUCT_UNAVAILABLE"| apiError
  postOrderPreview -->|"200 OrderSplit JSON"| httpClient
  postOrderPreview -->|"invalid body"| validationHandler
  ordersSvc -->|"create_order commit"| sqliteFile
  ordersSvc -->|"cancel_order commit"| sqliteFile
  ordersSvc -->|"order_created after commit"| fakeNotifier
```

`POST /orders/preview` is the only order route in the diagram above, and that route does not write or notify. The `create_order` and `cancel_order` edges are the other two writes on `services/orders`. The next diagram shows which routes take them:

```mermaid
flowchart LR
  httpClient["HTTP client"] -->|"POST /orders"| postOrder["post_order"]
  httpClient -->|"GET /orders/order_id"| getOrderDetail["get_order_detail"]
  httpClient -->|"GET /patient/orders"| getPatientOrders["get_patient_orders"]
  httpClient -->|"POST /orders/order_id/cancel"| postCancel["post_cancel_order"]

  postOrder --> requireRole["require_role"]
  getOrderDetail --> requireRole
  getPatientOrders --> requireRole
  postCancel --> requireRole
  requireRole -->|"401 or 403"| apiError["APIError handler"]

  postOrder -->|"get_notifier"| fakeNotifier["app.state.notifier"]
  postOrder --> ordersSvc["services/orders"]
  getOrderDetail --> ordersSvc
  getPatientOrders --> ordersSvc
  postCancel --> ordersSvc
  getOrderDetail --> requireOrder["require_order_access"]
  getPatientOrders --> requireOrder
  postCancel --> requireOrder
  requireOrder -->|"404 NOT_FOUND"| apiError

  ordersSvc --> getSession["get_session"]
  getSession -->|"Session"| sqliteFile["SQLite cerbo.db"]
  ordersSvc -->|"preview_order reads enabled lines"| sqliteFile
  ordersSvc -->|"resolved lines"| validateOrder["validate_order"]
  validateOrder -->|"PricingError"| pricingHandler["PricingError handler"]
  pricingHandler -->|"422 error JSON"| httpClient
  ordersSvc -->|"insert orders and order_lines, commit"| sqliteFile
  ordersSvc -->|"status cancelled and cancelled_at, commit"| sqliteFile
  ordersSvc -->|"order_created /orders/id"| fakeNotifier
  ordersSvc -->|"stored line"| lineAmounts["line_amounts"]

  postOrder -->|"422 INVALID_PATIENT or PRODUCT_UNAVAILABLE"| apiError
  postOrder -->|"invalid body"| validationHandler["RequestValidationError handler"]
  validationHandler -->|"422 VALIDATION_ERROR"| httpClient
  apiError -->|"error JSON"| httpClient
  postOrder -->|"200 order JSON"| httpClient
  getOrderDetail -->|"200 order JSON"| httpClient
  getPatientOrders -->|"200 order list"| httpClient
  postCancel -->|"200 order JSON"| httpClient
  postCancel -->|"409 ORDER_NOT_CANCELLABLE"| apiError
```

## Startup

`create_app` stores `database_url` on `app.state` before the lifespan runs. The default is `sqlite:///./cerbo.db` from `app.config`. The same function calls `build_notifier()` and stores that object on `app.state.notifier`. `build_notifier` returns a `FakeNotifier`. Nothing else constructs one. The lifespan does not replace the notifier.

The same function calls `build_payment_provider()` and stores that object on `app.state.payment_provider`. `build_payment_provider` returns a `FakePaymentProvider` and is the only production constructor. The lifespan does not replace the provider. The startup diagram gives that node no outgoing edge: no route reads it, and nothing calls `charge`.

1. `make_engine` opens that URL and attaches the SQLite connect and begin listeners.
2. `init_db` calls `Base.metadata.create_all`, which creates `users`, `products`, `provider_products`, `orders`, `order_lines`, and `ledger_entries` when they are missing.
3. `seed(session)` stages rows that are not already present, matched by `users.name`, `products.sku`, and the `provider_products` pair. The lifespan then `commit`s. That writes Dr. Maya Patel (provider), Jane Doe and Sam Lee (patients), Cerbo Admin (admin), products MAG-GLY, D3-K2, OMEGA3, and PROBIO50, and Dr. Patel's four enabled `provider_products` at suggested prices. Seed does not insert `orders`, `order_lines`, or `ledger_entries`.
4. `make_session_factory` is saved on `app.state.session_factory`.
5. Shutdown calls `engine.dispose()`.

## GET /health

1. **In.** `GET /health` with no body, query, or auth.
2. **Transform.** `health()` builds `{"status": "ok"}`. FastAPI serializes it as JSON and returns HTTP 200.
3. **Out.** `{"status": "ok"}` goes back to the caller.
4. **Storage.** This route does not open a session and does not read or write SQLite.

## GET /users

1. **In.** `GET /users` with no auth header.
2. **Read.** `get_session` opens a `Session` and closes it without committing. `list_users` runs `select(User).order_by(User.id)`.
3. **Out.** HTTP 200 and a JSON list of `{id, name, role}` for every row. After the startup seed, that list is the four users above, ordered by `id`.

## GET /me

1. **In.** `GET /me` and header `X-User-Id`.
2. **Resolve.** `current_user` uses the same request session. A missing header, a value that is blank after trimming, a value that is not an ASCII digit string, or an integer above the signed 64-bit maximum raises `APIError` before any lookup. Any other value is loaded with `session.get(User, id)`. An unknown id raises the same error.
3. **Out, success.** `me` returns the `User`. FastAPI serializes `{id, name, role}` and returns HTTP 200.
4. **Out, failure.** The app's `APIError` handler returns HTTP 401 and `{"error": {"code": "UNAUTHENTICATED", "message": "Missing or unknown user", "line_index": null}}`.
5. **Storage.** The route only reads `users`. The session closes with no commit.

The branch detail is in `flows/auth.md`.

## GET /products

1. **In.** `GET /products` and header `X-User-Id`.
2. **Auth.** `require_role("provider", "admin")` resolves `current_user` first. Failure is 401 `UNAUTHENTICATED` or 403 `FORBIDDEN` "Wrong role". A patient is forbidden. A provider and an admin are allowed.
3. **Read.** `list_products` runs `select(Product).order_by(Product.id)`. The session closes with no commit.
4. **Out.** HTTP 200 and a JSON list of `{id, sku, name, unit_cogs_cents, suggested_price_cents, stock_qty}`. After the startup seed, that is MAG-GLY, D3-K2, OMEGA3, and PROBIO50, ordered by `id`.

## GET /provider/products

1. **In.** `GET /provider/products` and header `X-User-Id`.
2. **Auth.** `require_role("provider")`. An admin or a patient is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Read.** `list_provider_products` joins `provider_products` to `products` where `provider_id` is the caller, ordered by `products.id`. `stock_qty` and `unit_cogs_cents` come from `products`. Rows for other providers are not included. A provider with no links gets `[]`.
4. **Out.** HTTP 200 and a JSON list of `{product_id, sku, name, enabled, default_price_cents, unit_cogs_cents, stock_qty}`. `enabled` is JSON `true` when the stored integer is `1`.
5. **Storage.** Read only. Stock is not writable on this route.

The read and update branches are in `flows/provider-products.md`.

## PUT /provider/products/{product_id}

1. **In.** `PUT /provider/products/{product_id}`, header `X-User-Id`, and a JSON body `{"enabled", "default_price_cents"}`.
2. **Auth.** `require_role("provider")`, same 401 and 403 outcomes as the provider list.
3. **Request validation.** `product_id` must be an integer. `ProviderProductUpdate` is strict: `enabled` is a JSON boolean and `default_price_cents` is a JSON integer. A bad path or body raises `RequestValidationError` before `update_provider_product`. The handler returns HTTP 422 and `{"error": {"code": "VALIDATION_ERROR", "message": "Invalid request", "line_index": null}}`. Nothing is written.
4. **Product lookup.** `update_provider_product` loads `products` by id. `UnknownProduct` is mapped in the route to `APIError` 404 `NOT_FOUND` "Not found". No price check and no write.
5. **Price check.** `validate_order` receives one `LineInput`: that `product_id`, `qty` 1, `unit_price_cents` equal to `default_price_cents`, and `unit_cogs_cents` from the product, plus `FEE_BPS_DEFAULT`. `PricingError` is not caught in the route. The app handler returns HTTP 422 and `{"error": {"code": <pricing code>, "message": <detail>, "line_index": <line index or null>}}`. Nothing is written.
6. **Write.** For this provider and product only, insert a `provider_products` row or update the existing one. The stored fields are `enabled` (`1` or `0`) and `default_price_cents`. `session.commit()` runs in the service. `products.stock_qty` and every other provider's rows stay as they were.
7. **Out.** HTTP 200 and one object with the same fields as a provider-list row. `stock_qty` is still the `products` value.

## POST /orders/preview

1. **In.** `POST /orders/preview`, header `X-User-Id`, and a JSON body `{"lines": [{"product_id", "qty", "unit_price_cents"}, ...]}`.
2. **Auth.** `require_role("provider")`. An admin or a patient is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Request validation.** `PreviewRequest` and `PreviewLineRequest` are strict. Each line's `product_id`, `qty`, and `unit_price_cents` must be JSON integers. A bad body raises `RequestValidationError` before `preview_order`. The handler returns HTTP 422 and `{"error": {"code": "VALIDATION_ERROR", "message": "Invalid request", "line_index": null}}`. Nothing is written.
4. **Resolve, in order.** `preview_order` does not commit and does not insert, update, or delete. For each line, a `product_id` outside `1..9223372036854775807` is unavailable and is not queried. Otherwise it loads `provider_products` for `(provider_id, product_id)`. A missing row or `enabled` other than `1` is unavailable and does not read `products`. An enabled row then loads `products` and copies `unit_cogs_cents`. A missing product is unavailable. `stock_qty` is not read. `orders`, `order_lines`, and `ledger_entries` are not read or written.
5. **Unavailable line.** If any earlier line already resolved, `validate_order` runs on that prefix at `FEE_BPS_DEFAULT` before the unavailable error. A `PricingError` from the prefix is the response: HTTP 422, `code` is the pricing code, `message` is `detail`, and `line_index` is that error's line index. If the prefix is valid, or there is no prefix, the route maps `ProductUnavailable` to `APIError` 422 `PRODUCT_UNAVAILABLE`, message "Product is not available for this provider.", and `line_index` of the unavailable line. Nothing is written.
6. **Every line resolved.** `validate_order` runs on the full list at `FEE_BPS_DEFAULT`. An empty `lines` array takes this path and raises `EMPTY_ORDER`. Any other `PricingError` uses the same 422 handler as the prefix. Nothing is written.
7. **Out.** HTTP 200 and the `OrderSplit` fields: `lines` of `{product_id, qty, unit_price_cents, unit_cogs_cents, line_total_cents, line_cogs_cents, line_margin_cents}`, plus `subtotal_cents`, `cogs_total_cents`, `fee_bps`, `platform_fee_cents`, and `provider_payout_cents`.

The branch detail is in `flows/order-preview.md`. This route does not call the notifier.

## POST /orders

1. **In.** `POST /orders`, header `X-User-Id`, and a JSON body `{"patient_id", "lines"}`. Each line is `{"product_id", "qty", "unit_price_cents"}`, the same shape as preview.
2. **Auth.** `require_role("provider")`. An admin or a patient is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Request validation.** `CreateOrderRequest` is strict. `patient_id` and each line's three fields must be JSON integers. A bad body raises `RequestValidationError` before `create_order`. The handler returns HTTP 422 `VALIDATION_ERROR`. Nothing is written.
4. **Notifier.** `get_notifier` reads `request.app.state.notifier` for this request. That is the instance `create_app` stored. The route passes it into `create_order`.
5. **Patient.** `create_order` checks the patient before preview. An id outside `1..9223372036854775807`, a missing `users` row, or a role other than `patient` raises `InvalidPatient`. The route maps that to 422 `INVALID_PATIENT`, message "Patient must be a patient user." Nothing is written.
6. **Price.** `preview_order` runs exactly as on `POST /orders/preview`, including `validate_order` at `FEE_BPS_DEFAULT`. `PricingError` is not caught in the route and becomes the same 422 pricing body. `ProductUnavailable` becomes 422 `PRODUCT_UNAVAILABLE` with `line_index`. Either one happens before the insert. `stock_qty` is not read.
7. **Names.** After the preview succeeds, `products.name` is copied for each line. A missing product raises `ProductUnavailable` and still writes nothing.
8. **Write.** One new `orders` row: the caller as `provider_id`, the requested `patient_id`, `status` `pending_payment`, `fee_bps` and the four order totals from the `OrderSplit`, `payment_ref` null, `created_at` as UTC `YYYY-MM-DDTHH:MM:SSZ`, `paid_at` null, `cancelled_at` null. `flush` assigns `orders.id`. Each line becomes an `order_lines` row: `product_id`, `product_name`, `qty`, `unit_price_cents`, and `unit_cogs_cents` from the snapshot. One `commit`. `products.stock_qty` is unchanged. No `ledger_entries` row is inserted.
9. **Notify.** After that commit, `order_created(order, "/orders/{id}")` runs. `FakeNotifier` prints `order created: /orders/{id}` and appends `(order.id, "/orders/{id}")` to `calls`. If `order_created` raises, the service logs the exception and still returns the order. The commit is not undone.
10. **Out.** HTTP 200 and the order JSON from `present_order`: stored order columns, `patient_link` `/orders/{id}`, and line totals from `line_amounts` on each stored line. The fee is the stored `fee_bps`, not a new calculation.

The branch detail is in `flows/orders.md`.

## GET /orders/{order_id}

1. **In.** `GET /orders/{order_id}` and header `X-User-Id`.
2. **Auth.** `require_role("provider", "patient")`. An admin is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Request validation.** `order_id` must be an integer. A non-integer path raises `RequestValidationError` before the handler: HTTP 422 `VALIDATION_ERROR`. Nothing is written.
4. **Load.** An id outside `1..9223372036854775807`, or `session.get(Order, order_id)` missing, raises `OrderNotFound`. The route maps that to 404 `NOT_FOUND` "Not found".
5. **Access.** `require_order_access` allows the order's `provider_id` or `patient_id`. Any other user gets the same 404. The body does not say which case failed.
6. **Present.** `order_lines` loads `order_lines` for that id, ordered by `order_lines.id`. `present_order` copies stored order columns. For each line, `line_amounts(unit_price_cents, unit_cogs_cents, qty)` supplies `line_total_cents`, `line_cogs_cents`, and `line_margin_cents`. It does not read the live catalog and does not call `compute_fee`.
7. **Out.** HTTP 200 and one order object: `{id, provider_id, patient_id, status, patient_link, created_at, paid_at, cancelled_at, payment_ref, lines, subtotal_cents, cogs_total_cents, fee_bps, platform_fee_cents, provider_payout_cents}`. `patient_link` is `/orders/{id}`.
8. **Storage.** Read only. The session closes with no commit.

## GET /patient/orders

1. **In.** `GET /patient/orders` and header `X-User-Id`. No order id and no body.
2. **Auth.** `require_role("patient")`. A provider or an admin is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Read.** `list_patient_orders` selects `orders` where `patient_id` is the caller, ordered by `orders.id`. For each row the route calls `require_order_access`, loads that order's lines, and `present_order`s them the same way as `GET /orders/{order_id}`.
4. **Out.** HTTP 200 and a JSON list of those order objects. A patient with no orders gets `[]`.
5. **Storage.** Read only.

## POST /orders/{order_id}/cancel

1. **In.** `POST /orders/{order_id}/cancel` and header `X-User-Id`. No body.
2. **Auth.** `require_role("provider")`. A patient or an admin is 403 `FORBIDDEN`. A missing or unknown user is 401 `UNAUTHENTICATED`.
3. **Request validation.** A non-integer `order_id` is 422 `VALIDATION_ERROR` before the handler. Nothing is written.
4. **Load and access.** The same `get_order` and `require_order_access` path as `GET /orders/{order_id}`. Missing or not owned is 404 `NOT_FOUND` "Not found", and `cancel_order` does not run.
5. **Status.** `cancel_order` writes only when `status` is `pending_payment`. It sets `status` to `cancelled` and `cancelled_at` to UTC `YYYY-MM-DDTHH:MM:SSZ`, then commits. Any other status raises `OrderNotCancellable`. The route maps that to 409 `ORDER_NOT_CANCELLABLE`, message "Order cannot be cancelled." That path does not write.
6. **Out.** HTTP 200 and the same order JSON as the get route, with `status` `cancelled` and the new `cancelled_at`. Line amounts still come from the stored lines through `line_amounts`.
7. **Unchanged.** No notifier call. `products.stock_qty` is unchanged. No `ledger_entries` row is inserted. `payment_ref` and `paid_at` stay as they were.

## Present in code, idle at runtime

`app.state.payment_provider` is the `FakePaymentProvider` from `build_payment_provider`. `charge(amount_cents, idempotency_key, payment_method)` would return a frozen `ChargeResult` (`approved`, `ref`, `decline_reason`). `fake_card_decline` declines with `ref` None and reason "Card declined." Every other method approves with `ref` `fake_{idempotency_key}`. The same key, amount, and method would replay the stored result and leave `charge_count` unchanged. An approval would stay sticky. A stored decline plus a different method, or the same method with a different amount, would be a new attempt. There is no lock. No route calls `charge`, so the attempt map stays empty. There is no payments service and no `POST /orders/{id}/pay`.

`ledger_entries` is created at startup and never inserted. No route sets `orders.payment_ref`, `orders.paid_at`, or `products.stock_qty` from an order. Fulfillment, dashboard, audit, and admin product routes are not registered.

`compute_split` and `compute_fee` run only when `validate_order` calls them. That happens on `PUT /provider/products/{product_id}` after the product is found, on `POST /orders/preview`, on `POST /orders` because `create_order` calls `preview_order`, and when `backend/tests/test_money.py` calls the money module directly.

`line_amounts` also runs from `present_order` for every order JSON response. Those display amounts are `unit_price_cents * qty`, `unit_cogs_cents * qty`, and the difference. They are not stored on `order_lines`.
