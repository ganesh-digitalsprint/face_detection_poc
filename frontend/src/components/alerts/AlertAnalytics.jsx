import { useMemo } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { USE_CASE_LABELS } from '../../api/alertServiceModel.js';
import './AlertAnalytics.css';

const COLORS = { indigo: '#4f5ee8', red: '#e11d48', orange: '#f97316', amber: '#f59e0b', slate: '#94a3b8' };
const SEVERITY_COLORS = { CRITICAL: COLORS.red, HIGH: COLORS.orange, WARNING: COLORS.amber, INFO: COLORS.indigo };
const number = (value) => Number(value || 0).toLocaleString();
const chartRowValue = (row, key) => row?.[key] ?? row?.payload?.[key];
const dayLabel = (value) => {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined,
    { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
};

function Card({ title, detail, children, className = '' }) {
  return <section className={`alert-analytics-card ${className}`}>
    <header><h3>{title}</h3>{detail && <span>{detail}</span>}</header>
    {children}
  </section>;
}

function Empty({ children = 'No alerts in this range.' }) {
  return <div className="alert-analytics-empty">{children}</div>;
}

function ChartFrame({ children, empty, emptyMessage }) {
  return empty ? <Empty>{emptyMessage}</Empty> : <div className="alert-analytics-chart">{children}</div>;
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return <div className="alert-analytics-tooltip"><strong>{label}</strong>{payload.map((item) =>
    <p key={item.dataKey} style={{ color: item.color }}>{item.name || item.dataKey}: {number(item.value)}</p>)}</div>;
}

export function AlertTrendsChart({ rows = [], rangeLabel = 'All dates', emptyMessage }) {
  const data = rows.map((row) => ({ ...row, dateLabel: dayLabel(row.date) }));
  const total = rows.reduce((count, row) => count + row.count, 0);
  return <Card title="Alerts over time" detail={`${number(total)} alerts · ${rangeLabel}`} className="alert-analytics-trend">
    <ChartFrame empty={!rows.length} emptyMessage={emptyMessage}><ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -22 }}>
        <defs><linearGradient id="alertTrendFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={COLORS.indigo} stopOpacity={0.2} /><stop offset="100%" stopColor={COLORS.indigo} stopOpacity={0.015} /></linearGradient></defs>
        <CartesianGrid stroke="#e7eaf4" vertical={false} />
        <XAxis dataKey="dateLabel" tick={{ fill: '#7480a0', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} />
        <YAxis allowDecimals={false} tick={{ fill: '#7480a0', fontSize: 10 }} axisLine={false} tickLine={false} />
        <Tooltip content={<ChartTooltip />} />
        <Area type="monotone" dataKey="count" name="All alerts" stroke={COLORS.indigo} strokeWidth={2.25} fill="url(#alertTrendFill)" activeDot={{ r: 4 }} />
      </AreaChart>
    </ResponsiveContainer></ChartFrame>
  </Card>;
}

export function AlertSeverityChart({ counts = {}, onSelect, emptyMessage }) {
  const rows = useMemo(() => ['CRITICAL', 'HIGH', 'WARNING', 'INFO'].map((name) => ({ name, value: counts[name] || 0 }))
    .filter((row) => row.value > 0), [counts]);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return <Card title="Severity mix" detail="Click to filter" className="alert-analytics-severity">
    <ChartFrame empty={!rows.length} emptyMessage={emptyMessage}><div className="alert-analytics-donut">
      <div className="alert-analytics-pie"><ResponsiveContainer width="100%" height="100%"><PieChart>
        <Pie data={rows} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="91%" paddingAngle={1.5} stroke="none" onClick={(row) => onSelect?.(chartRowValue(row, 'name'))}>
          {rows.map((row) => <Cell key={row.name} fill={SEVERITY_COLORS[row.name] || COLORS.slate} cursor="pointer" />)}
        </Pie><Tooltip content={<ChartTooltip />} />
      </PieChart></ResponsiveContainer><div className="alert-analytics-donut-total"><strong>{number(total)}</strong><span>in view</span></div></div>
      <div className="alert-analytics-legend">{rows.map((row) => <button key={row.name} type="button" onClick={() => onSelect?.(row.name)}>
        <i style={{ background: SEVERITY_COLORS[row.name] || COLORS.slate }} /><span>{row.name.charAt(0) + row.name.slice(1).toLowerCase()}</span><b>{number(row.value)}</b>
        <small>{total ? Math.round(row.value / total * 100) : 0}%</small>
      </button>)}</div>
    </div></ChartFrame>
  </Card>;
}

export function AlertsByUseCaseChart({ rows = [], onSelect, emptyMessage }) {
  const data = rows.map((row) => ({ ...row, label: USE_CASE_LABELS[row.use_case] || row.use_case }));
  return <Card title="Alerts by source" detail="Click a bar to filter" className="alert-analytics-source">
    <ChartFrame empty={!data.length} emptyMessage={emptyMessage}><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, bottom: 0, left: 0 }}>
      <XAxis type="number" allowDecimals={false} hide />
      <YAxis type="category" dataKey="label" width={112} tick={{ fill: '#39466e', fontSize: 10 }} axisLine={false} tickLine={false} />
      <Tooltip content={<ChartTooltip />} /><Bar dataKey="count" name="Alerts" fill={COLORS.indigo} background={{ fill: '#e9ecf6', radius: 5 }} radius={[5, 5, 5, 5]} barSize={8} onClick={(row) => onSelect?.(chartRowValue(row, 'use_case'))}>
        {data.map((row) => <Cell key={row.use_case} cursor="pointer" />)}
      </Bar>
    </BarChart></ResponsiveContainer></ChartFrame>
  </Card>;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

export function AlertHeatmap() {
  return <Card title="When alerts happen" detail="Day of week × hour" className="alert-analytics-heatmap">
    <div className="alert-heatmap-neutral" role="status" aria-label="Hourly alert aggregation unavailable">
      <div className="alert-heatmap-hours">{HOURS.map((hour) => <span key={hour}>{hour % 3 === 0 ? hour : ''}</span>)}</div>
      <div className="alert-heatmap-grid">{DAYS.map((day) => <div className="alert-heatmap-row" key={day}><span>{day}</span><div>{HOURS.map((hour) => <i key={hour} />)}</div></div>)}</div>
      <p>Hourly aggregation unavailable</p>
    </div>
  </Card>;
}

export default function AlertAnalytics({ summary = null, rangeLabel = 'All dates', onFilter = () => {}, loading = false, error = null,
  onRetry = null, errorMessage = '' }) {
  if (loading) return <section className="alert-analytics-state" aria-label="Loading alert analytics">Loading analytics…</section>;
  if (error) return <section className="alert-analytics-state alert-analytics-error" role="status">
    {errorMessage || 'Analytics are unavailable.'}{onRetry && <button type="button" onClick={onRetry}>Retry analytics</button>}
  </section>;
  const data = summary || {};
  const emptyMessage = summary ? 'No alerts match the selected filters.' : 'Analytics data unavailable.';
  return <div className="alert-analytics-grid" aria-label="Alert analytics">
    <AlertTrendsChart rows={data.by_day || []} rangeLabel={rangeLabel} emptyMessage={emptyMessage} />
    <AlertSeverityChart counts={data.by_severity || {}} emptyMessage={emptyMessage} onSelect={(value) => onFilter('severity', value)} />
    <AlertsByUseCaseChart rows={data.by_use_case || []} emptyMessage={emptyMessage} onSelect={(value) => onFilter('use_case', value)} />
    <AlertHeatmap />
  </div>;
}
