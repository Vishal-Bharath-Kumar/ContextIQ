# TASK-US035-04 — Trace Detail View + Export Component (Angular)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US035-04 |
| User Story | US-035 |
| Epic | EP-011 — AI Execution Replay |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Build the `TraceDetailComponent` — the Replay Explorer detail view page that renders a step-by-step pipeline timeline (AC-2) and all six required data sections: intent classification, retrieved source list with relevance scores, compression delta, governance decisions, selected model, and response summary (AC-3). An Export JSON button triggers a file download from `GET /v1/traces/{id}/export` (AC-6). The route is guarded by the same `auditorGuard` as the list view (AC-4).

## Implementation Details

**Technology:** Angular 17+, Angular Material (cards, expansion panels, progress bar, button), RxJS, `HttpClient`, standalone components

**File locations:**
- `src/app/admin/replay/trace-detail/trace-detail.component.ts`
- `src/app/admin/replay/trace-detail/trace-detail.component.html`
- `src/app/admin/replay/trace-detail/trace-detail.component.scss`
- `src/app/admin/replay/models/trace.models.ts` — extend with `TraceDetailResponse`, `TimelineStep`

---

### Extended TypeScript models

```typescript
// src/app/admin/replay/models/trace.models.ts  (extend existing file)

export interface RetrievedChunkSummary {
  chunk_id:             string;
  source_id:            string;
  relevance_score:      number;
  classification_label: string;
  redacted:             boolean;
  opa_denied:           boolean;
}

export interface CompressionDelta {
  tokens_before:  number;
  tokens_after:   number;
  chunks_before:  number;
  chunks_after:   number;
  reduction_pct:  number;
}

export interface GovernanceDecisionSummary {
  findings_count:      number;
  redacted_count:      number;
  opa_denied_count:    number;
  opa_bundle_version:  string;
  governance_blocked:  boolean;
}

export interface TimelineStep {
  step_number: number;
  node:        string;
  eval_ms:     number | null;
  metadata:    Record<string, unknown>;
}

export interface TraceDetailResponse {
  request_id:             string;
  user_id:                string;
  timestamp:              string;
  latency_ms:             number | null;
  // AC-3 fields
  intent_classification:  string;
  retrieved_sources:      RetrievedChunkSummary[];
  compression_delta:      CompressionDelta | null;
  governance_decisions:   GovernanceDecisionSummary;
  model_selected:         string | null;
  prompt_tokens:          number | null;
  completion_tokens:      number | null;
  response_summary:       string | null;
  // AC-2
  timeline:               TimelineStep[];
}
```

---

### `TraceDetailComponent`

```typescript
// src/app/admin/replay/trace-detail/trace-detail.component.ts
import {
  Component, OnInit, inject, signal,
} from '@angular/core';
import { CommonModule }       from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { MatCardModule }      from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatButtonModule }    from '@angular/material/button';
import { MatIconModule }      from '@angular/material/icon';
import { MatChipsModule }     from '@angular/material/chips';
import { MatTooltipModule }   from '@angular/material/tooltip';
import { MatDividerModule }   from '@angular/material/divider';

import { TraceService }        from '../trace.service';
import { TraceDetailResponse } from '../models/trace.models';


@Component({
  selector:    'app-trace-detail',
  standalone:  true,
  templateUrl: './trace-detail.component.html',
  styleUrls:   ['./trace-detail.component.scss'],
  imports: [
    CommonModule, RouterModule,
    MatCardModule, MatExpansionModule, MatProgressBarModule,
    MatButtonModule, MatIconModule, MatChipsModule,
    MatTooltipModule, MatDividerModule,
  ],
})
export class TraceDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly svc   = inject(TraceService);

  trace    = signal<TraceDetailResponse | null>(null);
  loading  = signal(true);
  error    = signal<string | null>(null);
  requestId = signal('');

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('requestId') ?? '';
    this.requestId.set(id);
    this.svc.getDetail(id).subscribe({
      next:  t  => { this.trace.set(t); this.loading.set(false); },
      error: () => {
        this.error.set('Failed to load trace. Please try again.');
        this.loading.set(false);
      },
    });
  }

  /** AC-6: Trigger browser download of the raw JSON export. */
  exportJson(): void {
    const url = this.svc.exportUrl(this.requestId());
    const a   = document.createElement('a');
    a.href    = url;
    a.download = `contextiq-trace-${this.requestId()}.json`;
    a.click();
    a.remove();
  }

  /** Compute relevance bar width (0–100) for progress bar. */
  relevanceWidth(score: number): number {
    return Math.round(Math.max(0, Math.min(1, score)) * 100);
  }
}
```

---

### Template

```html
<!-- trace-detail.component.html -->
<section class="trace-detail" aria-label="Execution trace detail">

  <!-- Back navigation -->
  <a mat-button routerLink="/admin/replay" aria-label="Back to Replay Explorer">
    <mat-icon>arrow_back</mat-icon> Back to list
  </a>

  <div *ngIf="loading()" role="status" aria-live="polite">
    <mat-progress-bar mode="indeterminate" aria-label="Loading trace" />
  </div>

  <p *ngIf="error()" class="error" role="alert">{{ error() }}</p>

  <ng-container *ngIf="trace() as t">

    <!-- Header -->
    <mat-card class="header-card">
      <mat-card-header>
        <mat-card-title>Trace {{ t.request_id }}</mat-card-title>
        <mat-card-subtitle>{{ t.timestamp | date:'long' }}</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <dl class="meta-list">
          <dt>User</dt>       <dd>{{ t.user_id }}</dd>
          <dt>Latency</dt>    <dd>{{ t.latency_ms !== null ? (t.latency_ms | number:'1.0-0') + ' ms' : '—' }}</dd>
        </dl>
      </mat-card-content>
      <mat-card-actions align="end">
        <!-- AC-6: Export button -->
        <button mat-stroked-button color="primary" (click)="exportJson()"
                aria-label="Export trace as JSON file">
          <mat-icon>download</mat-icon> Export JSON
        </button>
      </mat-card-actions>
    </mat-card>

    <!-- AC-3: Intent classification -->
    <mat-expansion-panel expanded aria-label="Intent classification">
      <mat-expansion-panel-header>
        <mat-panel-title>Intent Classification</mat-panel-title>
      </mat-expansion-panel-header>
      <p class="intent-badge">{{ t.intent_classification }}</p>
    </mat-expansion-panel>

    <!-- AC-2 + AC-3: Step-by-step pipeline timeline -->
    <mat-expansion-panel expanded aria-label="Pipeline timeline">
      <mat-expansion-panel-header>
        <mat-panel-title>Pipeline Timeline ({{ t.timeline.length }} steps)</mat-panel-title>
      </mat-expansion-panel-header>
      <ol class="timeline-list">
        <li *ngFor="let step of t.timeline" class="timeline-step">
          <span class="step-num">{{ step.step_number }}</span>
          <span class="step-node">{{ step.node }}</span>
          <span class="step-ms" *ngIf="step.eval_ms !== null">
            {{ step.eval_ms | number:'1.0-1' }} ms
          </span>
        </li>
      </ol>
    </mat-expansion-panel>

    <!-- AC-3: Retrieved sources with relevance scores -->
    <mat-expansion-panel aria-label="Retrieved sources">
      <mat-expansion-panel-header>
        <mat-panel-title>Retrieved Sources ({{ t.retrieved_sources.length }})</mat-panel-title>
      </mat-expansion-panel-header>
      <table class="sources-table" aria-label="Retrieved source chunks">
        <thead>
          <tr>
            <th scope="col">Chunk ID</th>
            <th scope="col">Source</th>
            <th scope="col">Classification</th>
            <th scope="col">Relevance</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let src of t.retrieved_sources">
            <td>{{ src.chunk_id | slice:0:8 }}…</td>
            <td>{{ src.source_id | slice:0:8 }}…</td>
            <td>{{ src.classification_label }}</td>
            <td>
              <mat-progress-bar mode="determinate"
                [value]="relevanceWidth(src.relevance_score)"
                [matTooltip]="(src.relevance_score | number:'1.3-3')"
                aria-label="Relevance score" />
            </td>
            <td>
              <mat-chip *ngIf="src.redacted"    color="warn"    highlighted>Redacted</mat-chip>
              <mat-chip *ngIf="src.opa_denied"  color="warn"    highlighted>OPA Denied</mat-chip>
              <mat-chip *ngIf="!src.redacted && !src.opa_denied" color="primary" highlighted>OK</mat-chip>
            </td>
          </tr>
        </tbody>
      </table>
    </mat-expansion-panel>

    <!-- AC-3: Compression delta -->
    <mat-expansion-panel *ngIf="t.compression_delta" aria-label="Compression delta">
      <mat-expansion-panel-header>
        <mat-panel-title>Compression Delta</mat-panel-title>
      </mat-expansion-panel-header>
      <dl class="meta-list">
        <dt>Tokens before</dt><dd>{{ t.compression_delta!.tokens_before | number }}</dd>
        <dt>Tokens after</dt> <dd>{{ t.compression_delta!.tokens_after  | number }}</dd>
        <dt>Reduction</dt>    <dd>{{ t.compression_delta!.reduction_pct }}%</dd>
        <dt>Chunks before</dt><dd>{{ t.compression_delta!.chunks_before }}</dd>
        <dt>Chunks after</dt> <dd>{{ t.compression_delta!.chunks_after  }}</dd>
      </dl>
    </mat-expansion-panel>

    <!-- AC-3: Governance decisions -->
    <mat-expansion-panel aria-label="Governance decisions">
      <mat-expansion-panel-header>
        <mat-panel-title>Governance Decisions</mat-panel-title>
      </mat-expansion-panel-header>
      <dl class="meta-list">
        <dt>Blocked</dt>        <dd>{{ t.governance_decisions.governance_blocked ? 'Yes' : 'No' }}</dd>
        <dt>Findings</dt>       <dd>{{ t.governance_decisions.findings_count }}</dd>
        <dt>Redacted</dt>       <dd>{{ t.governance_decisions.redacted_count }}</dd>
        <dt>OPA denied</dt>     <dd>{{ t.governance_decisions.opa_denied_count }}</dd>
        <dt>Bundle version</dt> <dd>{{ t.governance_decisions.opa_bundle_version }}</dd>
      </dl>
    </mat-expansion-panel>

    <!-- AC-3: Model selected -->
    <mat-expansion-panel aria-label="Model routing">
      <mat-expansion-panel-header>
        <mat-panel-title>Model Routing</mat-panel-title>
      </mat-expansion-panel-header>
      <dl class="meta-list">
        <dt>Model</dt>             <dd>{{ t.model_selected ?? '—' }}</dd>
        <dt>Prompt tokens</dt>     <dd>{{ t.prompt_tokens     !== null ? (t.prompt_tokens     | number) : '—' }}</dd>
        <dt>Completion tokens</dt> <dd>{{ t.completion_tokens !== null ? (t.completion_tokens | number) : '—' }}</dd>
      </dl>
    </mat-expansion-panel>

    <!-- AC-3: Response summary -->
    <mat-expansion-panel *ngIf="t.response_summary" aria-label="Response summary">
      <mat-expansion-panel-header>
        <mat-panel-title>Response Summary</mat-panel-title>
      </mat-expansion-panel-header>
      <p class="response-text">{{ t.response_summary }}</p>
    </mat-expansion-panel>

  </ng-container>
</section>
```

## Acceptance Criteria

- [ ] Navigating to `/admin/replay/:id` without `AUDITOR` or `ADMIN` role redirects to `/403` (AC-4, via `auditorGuard` on the route)
- [ ] Template renders all six AC-3 sections: intent, sources, compression delta, governance, model, response summary
- [ ] Source table shows a `mat-progress-bar` for relevance score and chip labels `Redacted` / `OPA Denied` / `OK` (AC-3)
- [ ] Timeline `<ol>` has one `<li>` per `TimelineStep` in the correct order (AC-2)
- [ ] Export JSON button calls `TraceService.exportUrl()` and creates a `<a download>` programmatically (AC-6)
- [ ] `aria-label` attributes are present on all interactive elements and data tables (WCAG 2.1 AA)

## Dependencies

- TASK-US035-01 (`TraceDetailResponse`, sub-schemas)
- TASK-US035-02 (`GET /v1/traces/{id}`, `GET /v1/traces/{id}/export`)
- TASK-US035-03 (`auditorGuard`, `TraceService`, route config)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] No `ng lint` or `tsc --strict` errors
- [ ] WCAG 2.1 AA: all tables and interactive controls have accessible labels
