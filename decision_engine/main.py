import argparse
import json
import os
from uuid import UUID
from decision_engine.clients.supabase_client import SupabaseClient
from decision_engine.config.settings import Settings, scoring_config
from decision_engine.config.logging import configure
from decision_engine.repositories.store import Repository
from decision_engine.services.decision_service import DecisionService, TRIGGERS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate strategy or queue CRM-approved recommendations")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--organization", type=lambda s: str(UUID(s)))
    group.add_argument("--all", action="store_true")
    parser.add_argument("--trigger", type=str.upper, choices=TRIGGERS, default="MANUAL_REQUEST")
    parser.add_argument("--queue-approved", action="store_true", help="Create handoff requests only; never execute them")
    args = parser.parse_args(argv)
    if not args.organization and not args.all and args.trigger != "SCHEDULED_REVIEW":
        parser.error("Select --organization or --all (scheduled_review defaults to all)")
    try:
        settings = Settings.from_env()
        configure(settings.log_level)
        config = scoring_config(os.getenv("DECISION_SCORING_FILE") or None)
        repository = Repository(SupabaseClient(settings), config)
        service = DecisionService(repository, config)
        organizations = [{"id": args.organization}] if args.organization else repository.organizations()
        failed = False
        for organization in organizations:
            try:
                result = repository.dispatch(organization["id"]) if args.queue_approved else service.run(organization["id"], args.trigger)
                if isinstance(result, dict) and result.get("status") == "PARTIAL":
                    failed = True
                print(json.dumps({"organization_id": organization["id"], "result": result if args.queue_approved else {"run_id": result["run_id"], "status": result["status"]}}))
            except Exception as error:
                failed = True
                print(json.dumps({"organization_id": organization["id"], "error_type": type(error).__name__}))
        return 1 if failed else 0
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
