// The a11y_reports table from the site's Drizzle schema (the rest of the
// site's schema is not part of this extraction).
import { pgEnum, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const a11yReportStatus = pgEnum("a11y_report_status", [
  "pending",
  "investigating",
  "fix_proposed",
  "fix_deployed",
  "dismissed",
]);

export const a11yReports = pgTable("a11y_reports", {
  id: uuid("id").primaryKey().defaultRandom(),
  url: text("url").notNull(),
  description: text("description").notNull(),
  userAgent: text("user_agent"),
  ip: text("ip"),
  reporterEmail: text("reporter_email"),
  status: a11yReportStatus("status").notNull().default("pending"),
  agentRunId: text("agent_run_id"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
