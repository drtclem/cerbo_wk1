_Last updated: 2026-10-06 — T12: /products is ProductsPage, with stock, enable, price save, and preview._

# Frontend shell

`src/main.tsx` mounts `BrowserRouter`, Pico CSS, and `theme.css`, then renders `App`. `src/api/client.ts` calls relative URLs under `/api`. The Vite dev server proxies only `/api` to `http://127.0.0.1:8000` and strips the `/api` prefix. A document request such as `/orders/5` or `/products` is not proxied. It stays in the SPA. See `data-flow.md`.

## Load

```mermaid
sequenceDiagram
  participant Browser
  participant App as "frontend App"
  participant Store as "localStorage"
  participant Proxy as "Vite /api proxy"
  participant API as "app.main"

  Browser->>App: document URL
  App->>Proxy: GET /api/users
  Note over App,Proxy: no X-User-Id
  Proxy->>API: GET /users
  alt error envelope
    API-->>Proxy: error JSON
    Proxy-->>App: error JSON
    App-->>Browser: alert code and message
  else user list
    API-->>Proxy: 200 user list JSON
    Proxy-->>App: user list JSON
    App->>Store: write cerbo.userId
    App->>Proxy: GET /api/me
    Note over App,Proxy: X-User-Id is the stored id
    Proxy->>API: GET /me
    alt error envelope
      API-->>Proxy: error JSON
      Proxy-->>App: error JSON
      App-->>Browser: alert code and message
    else user JSON
      API-->>Proxy: 200 user JSON
      Proxy-->>App: user JSON
      App-->>Browser: Signed in as name, role
    end
  end
```

`App` calls `apiGet("/users", null)` on mount. `RoleSwitcher` renders that list in a select. The stored id is `localStorage` key `cerbo.userId` when the value is digits and matches a listed user. Otherwise it is the first user. An empty list throws `Error` "No users" and does not call `GET /me`. `App` writes the chosen id, then calls `apiGet("/me", userId)`.

A response that is not OK is read as JSON. When `error.code` and `error.message` are strings and `error.line_index` is null or a number, `apiGet` throws `ApiError` with `code`, `message`, and `lineIndex`. The header alert shows `code: message`. Any other failure becomes `Error` "Request failed".

`/` renders "Loading account…" until `GET /me` returns. It then replaces the location with that role's first page.

## Role and routes

```mermaid
flowchart LR
  role["me.role"] --> navFor["navFor"]
  navFor --> provider["provider"]
  navFor --> patient["patient"]
  navFor --> admin["admin"]
  provider --> products["/products"]
  provider --> newOrder["/orders/new"]
  provider --> dashboard["/dashboard"]
  patient --> myOrders["/patient/orders"]
  admin --> stock["/admin/products"]
  products --> productsPage["ProductsPage"]
  newOrder --> placeholder["PlaceholderPage"]
  dashboard --> placeholder
  myOrders --> placeholder
  stock --> placeholder
```

The link labels are Products, New order, Dashboard, My orders, and Stock & COGS. `/products` renders `ProductsPage` with the signed-in user id. `/orders/new`, `/dashboard`, `/patient/orders`, and `/admin/products` still render `PlaceholderPage` with that title and the signed-in name and role. Those placeholder pages do not fetch. `/orders/:orderId` and `/orders/:orderId/audit` are not registered, so those document URLs have no page. The header still renders.

## Products

`ProductsPage` calls `apiGet("/provider/products", userId)` when it mounts. The client fetches `/api/provider/products` with `X-User-Id`. The proxy strips `/api`. A failed list shows the error message and no rows. Each row shows `name`, `sku`, and stock as `{n} in stock` or `Out of stock`. Stock is not an input and is not sent back.

```mermaid
sequenceDiagram
  participant Browser
  participant Page as ProductsPage
  participant Money as "money.ts"
  participant Proxy as "Vite /api proxy"
  participant API as "app.main"

  Browser->>Page: open /products
  Page->>Proxy: GET /api/provider/products
  Note over Page,Proxy: X-User-Id is the signed-in id
  Proxy->>API: GET /provider/products
  API-->>Proxy: 200 provider product JSON
  Proxy-->>Page: product JSON
  Page-->>Browser: name, sku, and stock text

  alt Enabled checkbox changes
    Page->>Proxy: PUT /api/provider/products/id
    Note over Page,Proxy: enabled and last saved default_price_cents
    Proxy->>API: PUT /provider/products/id
    API-->>Proxy: 200 product JSON
    Proxy-->>Page: updated product JSON
  else price text changes and the row is disabled
    Note over Page: no preview request
  else price text changes and the row is enabled
    Page->>Money: parseDollarsToCents after 300ms
    alt invalid dollars
      Money-->>Page: Invalid dollar amount
      Page-->>Browser: Invalid dollar amount
    else cents
      Page->>Proxy: POST /api/orders/preview
      Note over Page,Proxy: one line, qty 1, typed cents
      Proxy->>API: POST /orders/preview
      alt PRODUCT_UNAVAILABLE
        API-->>Proxy: 422 PRODUCT_UNAVAILABLE
        Proxy-->>Page: error JSON
        Note over Page: no you-receive line
      else other error
        API-->>Proxy: error JSON
        Proxy-->>Page: error JSON
        Page-->>Browser: error message
      else OrderSplit
        API-->>Proxy: 200 OrderSplit JSON
        Proxy-->>Page: provider_payout_cents
        Page->>Money: formatCents
        Page-->>Browser: you receive that amount at qty 1
      end
    end
  else Save
    Page->>Money: parseDollarsToCents
    alt invalid dollars
      Money-->>Page: Invalid dollar amount
      Page-->>Browser: Invalid dollar amount
    else cents
      Page->>Proxy: PUT /api/provider/products/id
      Note over Page,Proxy: checkbox enabled and parsed cents
      Proxy->>API: PUT /provider/products/id
      API-->>Proxy: 200 product JSON
      Proxy-->>Page: updated product JSON
    end
  end
```

The checkbox PUT does not send the unsaved typed price. Turning a row off clears the you-receive line and the preview error. `PRODUCT_UNAVAILABLE` from preview is ignored: the row shows no payout and no preview error. Any other preview or save failure shows the error message. The browser does not compute the split.

```mermaid
sequenceDiagram
  participant Browser
  participant Switch as RoleSwitcher
  participant App as "frontend App"
  participant Store as "localStorage"
  participant Proxy as "Vite /api proxy"
  participant API as "GET /me"

  Browser->>Switch: select a user
  Switch->>App: onChange id
  App->>Store: write cerbo.userId
  alt role changed and path is not in the new nav
    App->>Browser: go to that role's first page
  else same role or path still in the nav
    App->>Browser: stay on the path
  end
  App->>Proxy: GET /api/me, X-User-Id
  Proxy->>API: GET /me
  API-->>Proxy: 200 user JSON
  Proxy-->>App: user JSON
  App-->>Browser: header and nav for the role
```

The first page is `/products` for a provider, `/patient/orders` for a patient, and `/admin/products` for an admin. A role change whose current path is already in the new nav does not navigate. The redirect uses the role on the user already loaded from `GET /users`. `GET /me` then runs again because the selected id changed. A failed `GET /me` throws `ApiError` the same way as the first load.

## Dollars and generated types

`src/lib/money.ts` exports `parseDollarsToCents` and `formatCents`. `ProductsPage` calls them. `parseDollarsToCents` accepts an optional leading `$` and commas only as thousands separators, then returns integer cents. A comma that is not a thousands separator is invalid. `formatCents` prints `$` and groups thousands. Neither function computes a split. The you-receive line formats `provider_payout_cents` from `POST /orders/preview`.

`npm run gen:api` runs `openapi-typescript` against `http://127.0.0.1:8000/openapi.json` and writes `src/api/schema.ts`. `RoleSwitcher` imports `UserResponse` from that file. `ProductsPage` imports `ProviderProductResponse` and `PreviewResponse`. The running page does not request the OpenAPI document.
