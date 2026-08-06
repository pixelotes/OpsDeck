from src import create_app
from src.models import Module

def verify():
    app = create_app()
    with app.app_context():
        # Check if modules were seeded
        modules = Module.query.all()
        print(f"Total modules found: {len(modules)}")
        for m in modules:
            print(f"- {m.name} ({m.slug})")
        
        expected_slugs = [
            "health_dashboard", "procurement", "core_inventory", "operations",
            "roadmaps", "risk_governance", "compliance", "knowledge_policy",
            "finance", "hr_people", "communications", "administration", "settings"
        ]
        
        found_slugs = [m.slug for m in modules]
        missing = [s for s in expected_slugs if s not in found_slugs]
        
        if not missing:
            print("✓ All expected modules are present.")
        else:
            print(f"✗ Missing modules: {missing}")

if __name__ == "__main__":
    verify()
