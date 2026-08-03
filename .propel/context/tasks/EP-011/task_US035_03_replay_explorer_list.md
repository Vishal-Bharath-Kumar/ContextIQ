# TASK-US035-03 — Replay Explorer List View (Angular Search Filters + Paginated Table)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US035-03 |
| User Story | US-035 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Build the `ReplayExplorerComponent` — the Replay Explorer list-view page in the Admin Portal that presents a paginated, searchable table of execution traces (AC-1). Users can filter by `user_id`, date range, intent type, model used, and governance decision outcome. The component is protected by an `AuditorGuard` that restricts access to `AUDITOR` and `ADMIN` roles (AC-4). Each row navigates to the trace detail view (TASK-US035-04). Connects to `GET /v1/traces` (TASK-US035-02).

## Implementation Details

**Technology:** Angular 17+, Angular Material (table, form fields, date picker, select), RxJS, `HttpClient`, standalone components

**File locations:**
- `src/app/admin/replay/replay-explorer/replay-explorer.component.ts`
- `src/app/admin/replay/replay-explorer/replay-explorer.component.html`
- `src/app/admin/replay/replay-explorer/replay-explorer.component.scss`
- `src/app/admin/replay/trace.service.ts` — `TraceService` (HTTP client wrapper)
- `src/app/admin/replay/models/trace.models.ts` — TypeScript interfaces matching API DTOs
- `src/app/admin/replay/guards/auditor.guard.ts` — `AuditorGuard`
- `src/app/admin/replay/replay.routes.ts` — lazy-loaded route config

---

### TypeScript models (mirrors API DTOs)

```typescript
// src/app/admin/replay/models/trace.models.ts

export interface TraceListItem {
  request_id:          string;
  user_id:             string;
  timestamp:           string;   // ISO-8601
  intent:              string;
  model_selected:      string | null;
  governance_blocked:  boolean;
  opa_denied_count:    number;
  object_key:          string;
}

export interface TraceListResponse {
  items:   TraceListItem[];
  total:   number;
  limit:   number;
  offset:  number;
}

export interface TraceSearchParams {
  user_id?:            string;
  intent?:             string;
  model_selected?:     string;
  governance_blocked?: boolean;
  from?:               string;   // ISO-8601
  to?:                 string;
  limit:               number;
  offset:              number;
}
```

---

### `TraceService`

```typescript
// src/app/admin/replay/trace.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env/environment';
import { TraceListResponse, TraceSearchParams, TraceDetailResponse } from './models/trace.models';

@Injectable({ providedIn: 'root' })
export class TraceService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBase}/v1/traces`;

  search(params: TraceSearchParams): Observable<TraceListResponse> {
    let httpParams = new HttpParams()
      .set('limit',  params.limit.toString())
      .set('offset', params.offset.toString());

    if (params.user_id)            httpParams = httpParams.set('user_id',            params.user_id);
    if (params.intent)             httpParams = httpParams.set('intent',             params.intent);
    if (params.model_selected)     httpParams = httpParams.set('model_selected',     params.model_selected);
    if (params.governance_blocked !== undefined) {
      httpParams = httpParams.set('governance_blocked', String(params.governance_blocked));
    }
    if (params.from) httpParams = httpParams.set('from', params.from);
    if (params.to)   httpParams = httpParams.set('to',   params.to);

    return this.http.get<TraceListResponse>(this.base, { params: httpParams });
  }

  getDetail(requestId: string): Observable<TraceDetailResponse> {
    return this.http.get<TraceDetailResponse>(`${this.base}/${requestId}`);
  }

  exportUrl(requestId: string): string {
    return `${this.base}/${requestId}/export`;
  }
}
```

---

### `AuditorGuard`

```typescript
// src/app/admin/replay/guards/auditor.guard.ts
import { inject }                from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService }           from '@core/auth/auth.service';   // existing

export const auditorGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);
  // AC-4: allow AUDITOR or ADMIN (case-insensitive)
  const roles  = (auth.currentUserRoles ?? []).map((r: string) => r.toLowerCase());
  if (roles.includes('auditor') || roles.includes('admin')) {
    return true;
  }
  return router.parseUrl('/403');
};
```

---

### `ReplayExplorerComponent`

```typescript
// src/app/admin/replay/replay-explorer/replay-explorer.component.ts
import {
  Component, OnInit, OnDestroy, inject, signal, computed,
} from '@angular/core';
import { CommonModule }        from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup } from '@angular/forms';
import { RouterModule }        from '@angular/router';
import { MatTableModule }      from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatFormFieldModule }  from '@angular/material/form-field';
import { MatInputModule }      from '@angular/material/input';
import { MatSelectModule }     from '@angular/material/select';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatButtonModule }     from '@angular/material/button';
import { MatChipsModule }      from '@angular/material/chips';
import { Subject }             from 'rxjs';
import { takeUntil, debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { TraceService }   from '../trace.service';
import { TraceListItem }  from '../models/trace.models';

const DISPLAYED_COLUMNS = [
  'timestamp', 'user_id', 'intent', 'model_selected',
  'governance_blocked', 'opa_denied_count', 'actions',
] as const;

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector:    'app-replay-explorer',
  standalone:  true,
  templateUrl: './replay-explorer.component.html',
  styleUrls:   ['./replay-explorer.component.scss'],
  imports: [
    CommonModule, ReactiveFormsModule, RouterModule,
    MatTableModule, MatPaginatorModule, MatFormFieldModule,
    MatInputModule, MatSelectModule, MatDatepickerModule,
    MatButtonModule, MatChipsModule,
  ],
})
export class ReplayExplorerComponent implements OnInit, OnDestroy {
  private readonly svc     = inject(TraceService);
  private readonly fb      = inject(FormBuilder);
  private readonly destroy$ = new Subject<void>();

  readonly columns         = DISPLAYED_COLUMNS;
  readonly pageSizeOptions = PAGE_SIZE_OPTIONS;

  // AC-1 filter form
  filterForm: FormGroup = this.fb.group({
    user_id:            [''],
    intent:             [''],
    model_selected:     [''],
    governance_blocked: [null],
    from:               [null],
    to:                 [null],
  });

  rows    = signal<TraceListItem[]>([]);
  total   = signal(0);
  loading = signal(false);
  pageIndex = signal(0);
  pageSize  = signal(50);

  ngOnInit(): void {
    this._load();

    // Re-query 400 ms after last filter change
    this.filterForm.valueChanges.pipe(
      debounceTime(400),
      distinctUntilChanged(),
      takeUntil(this.destroy$),
    ).subscribe(() => {
      this.pageIndex.set(0);
      this._load();
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this._load();
  }

  private _load(): void {
    this.loading.set(true);
    const v   = this.filterForm.value;
    const params = {
      ...v,
      from:   v.from  ? new Date(v.from).toISOString()  : undefined,
      to:     v.to    ? new Date(v.to).toISOString()    : undefined,
      limit:  this.pageSize(),
      offset: this.pageIndex() * this.pageSize(),
    };
    this.svc.search(params).pipe(takeUntil(this.destroy$)).subscribe({
      next: res => {
        this.rows.set(res.items);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }
}
```

---

### Template (key structure)

```html
<!-- replay-explorer.component.html -->
<section class="replay-explorer">
  <h1 class="page-title">Replay Explorer</h1>

  <!-- AC-1: Search filter controls -->
  <form [formGroup]="filterForm" class="filter-bar" role="search" aria-label="Trace search filters">
    <mat-form-field appearance="outline">
      <mat-label>User ID</mat-label>
      <input matInput formControlName="user_id" aria-label="Filter by user ID" />
    </mat-form-field>

    <mat-form-field appearance="outline">
      <mat-label>Intent</mat-label>
      <input matInput formControlName="intent" aria-label="Filter by intent type" />
    </mat-form-field>

    <mat-form-field appearance="outline">
      <mat-label>Model</mat-label>
      <input matInput formControlName="model_selected" aria-label="Filter by model" />
    </mat-form-field>

    <mat-form-field appearance="outline">
      <mat-label>Governance</mat-label>
      <mat-select formControlName="governance_blocked" aria-label="Filter by governance decision">
        <mat-option [value]="null">Any</mat-option>
        <mat-option [value]="true">Blocked</mat-option>
        <mat-option [value]="false">Allowed</mat-option>
      </mat-select>
    </mat-form-field>

    <mat-form-field appearance="outline">
      <mat-label>From date</mat-label>
      <input matInput [matDatepicker]="fromPicker" formControlName="from" aria-label="From date" />
      <mat-datepicker-toggle matIconSuffix [for]="fromPicker" />
      <mat-datepicker #fromPicker />
    </mat-form-field>

    <mat-form-field appearance="outline">
      <mat-label>To date</mat-label>
      <input matInput [matDatepicker]="toPicker" formControlName="to" aria-label="To date" />
      <mat-datepicker-toggle matIconSuffix [for]="toPicker" />
      <mat-datepicker #toPicker />
    </mat-form-field>
  </form>

  <!-- Results table -->
  <mat-table [dataSource]="rows()" aria-label="Execution trace results">
    <ng-container matColumnDef="timestamp">
      <mat-header-cell *matHeaderCellDef>Timestamp</mat-header-cell>
      <mat-cell *matCellDef="let row">{{ row.timestamp | date:'medium' }}</mat-cell>
    </ng-container>

    <ng-container matColumnDef="user_id">
      <mat-header-cell *matHeaderCellDef>User</mat-header-cell>
      <mat-cell *matCellDef="let row">{{ row.user_id }}</mat-cell>
    </ng-container>

    <ng-container matColumnDef="intent">
      <mat-header-cell *matHeaderCellDef>Intent</mat-header-cell>
      <mat-cell *matCellDef="let row">{{ row.intent }}</mat-cell>
    </ng-container>

    <ng-container matColumnDef="model_selected">
      <mat-header-cell *matHeaderCellDef>Model</mat-header-cell>
      <mat-cell *matCellDef="let row">{{ row.model_selected ?? '—' }}</mat-cell>
    </ng-container>

    <ng-container matColumnDef="governance_blocked">
      <mat-header-cell *matHeaderCellDef>Governance</mat-header-cell>
      <mat-cell *matCellDef="let row">
        <mat-chip [color]="row.governance_blocked ? 'warn' : 'primary'" highlighted>
          {{ row.governance_blocked ? 'Blocked' : 'Allowed' }}
        </mat-chip>
      </mat-cell>
    </ng-container>

    <ng-container matColumnDef="opa_denied_count">
      <mat-header-cell *matHeaderCellDef>Denied chunks</mat-header-cell>
      <mat-cell *matCellDef="let row">{{ row.opa_denied_count }}</mat-cell>
    </ng-container>

    <!-- AC-2: row links to detail view -->
    <ng-container matColumnDef="actions">
      <mat-header-cell *matHeaderCellDef></mat-header-cell>
      <mat-cell *matCellDef="let row">
        <a mat-button color="primary"
           [routerLink]="['/admin/replay', row.request_id]"
           aria-label="View trace detail">
          View
        </a>
      </mat-cell>
    </ng-container>

    <mat-header-row *matHeaderRowDef="columns" />
    <mat-row *matRowDef="let row; columns: columns;"
             [routerLink]="['/admin/replay', row.request_id]"
             style="cursor:pointer" />
  </mat-table>

  <mat-paginator
    [length]="total()"
    [pageSize]="pageSize()"
    [pageSizeOptions]="pageSizeOptions"
    (page)="onPage($event)"
    aria-label="Trace list pagination" />
</section>
```

---

### Route configuration

```typescript
// src/app/admin/replay/replay.routes.ts
import { Routes }            from '@angular/router';
import { auditorGuard }      from './guards/auditor.guard';

export const REPLAY_ROUTES: Routes = [
  {
    path:       '',
    canActivate: [auditorGuard],           // AC-4
    loadComponent: () =>
      import('./replay-explorer/replay-explorer.component')
        .then(m => m.ReplayExplorerComponent),
  },
  {
    path:       ':requestId',
    canActivate: [auditorGuard],
    loadComponent: () =>
      import('./trace-detail/trace-detail.component')
        .then(m => m.TraceDetailComponent),
  },
];
```

## Acceptance Criteria

- [ ] Navigating to `/admin/replay` without `AUDITOR` or `ADMIN` role redirects to `/403` (AC-4)
- [ ] `AuditorGuard` accepts `auditor`, `AUDITOR`, `admin`, `ADMIN` (case-insensitive, AC-4)
- [ ] Filter form debounces at 400 ms — no API call on every keystroke
- [ ] Date range pickers populate `from` / `to` query params in ISO-8601 format (AC-1)
- [ ] Each table row has a `[routerLink]` navigating to `/admin/replay/{request_id}` (AC-2)
- [ ] Paginator correctly passes `limit` / `offset` to `TraceService.search()` on page change

## Dependencies

- TASK-US035-01 (`TraceListItem`, `TraceListResponse`, `TraceSearchParams`)
- TASK-US035-02 (`GET /v1/traces` endpoint contract)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] No `ng lint` or `tsc --strict` errors
- [ ] WCAG 2.1 AA: all form controls have `aria-label`; table has `aria-label`
