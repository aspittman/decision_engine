import argparse
import json
import os
from uuid import UUID
from decision_engine.clients.crm_client import CRMClient
from decision_engine.config.settings import CRMSettings, scoring_config
from decision_engine.config.logging import configure
from decision_engine.repositories.crm import CRMRepository
from decision_engine.services.decision_service import DecisionService, TRIGGERS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate strategy and submit recommendations for CRM review")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--organization", type=lambda s: str(UUID(s)))
    group.add_argument("--all", action="store_true")
    parser.add_argument("--trigger", type=str.upper, choices=TRIGGERS, default="MANUAL_REQUEST")
    from decision_engine.services.registry import SERVICES
    parser.add_argument('--service-id', choices=SERVICES)
    parser.add_argument('--decision-type', type=str.upper)
    parser.add_argument('--workflow-context', help='JSON containing authoritative upstream workflow identifiers')
    args = parser.parse_args(argv)
    if not args.organization and not args.all and args.trigger != "SCHEDULED_REVIEW":
        parser.error("Select --organization or --all (scheduled_review defaults to all)")
    try:
        settings = CRMSettings.from_env()
        configure(settings.log_level)
        config = scoring_config(os.getenv("DECISION_SCORING_FILE") or None)
        repository = CRMRepository(CRMClient(settings.api_url, settings.api_secret), config)
        service = DecisionService(repository, config)
        organizations = [{"id": args.organization}] if args.organization else repository.organizations()
        failed = False
        for organization in organizations:
            try:
                result = service.run(organization["id"], args.trigger, service_id=args.service_id,
                                     decision_type=args.decision_type,
                                     workflow_context=json.loads(args.workflow_context) if args.workflow_context else None)
                if isinstance(result, dict) and result.get("status") == "PARTIAL":
                    failed = True
                print(json.dumps({"organization_id": organization["id"], "result": {"run_id": result["run_id"], "status": result["status"]}}))
            except Exception as error:
                failed = True
                print(json.dumps({"organization_id": organization["id"], "error_type": type(error).__name__}))
        return 1 if failed else 0
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
