CREATE TYPE "public"."a11y_report_status" AS ENUM('pending', 'investigating', 'fix_proposed', 'fix_deployed', 'dismissed');

CREATE TABLE "a11y_reports" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "url" text NOT NULL,
  "description" text NOT NULL,
  "user_agent" text,
  "ip" text,
  "status" "a11y_report_status" NOT NULL DEFAULT 'pending',
  "agent_run_id" text,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
