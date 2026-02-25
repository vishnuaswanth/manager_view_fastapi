# V2 Architecture Diagrams

This folder contains Mermaid diagram files (.mmd) for the V2 Weekly Capacity & Multi-Group Resource Tracking system.

## Diagram Files

### Data Flow Diagrams
| File | Description |
|------|-------------|
| `data_flow.mmd` | High-level data flow from input to output |
| `capacity_calculation.mmd` | Capacity calculation formula flow |
| `report_generation.mmd` | Report generation process |
| `data_migration.mmd` | V1 to V2 data migration flow |

### Allocation Diagrams
| File | Description |
|------|-------------|
| `allocation_process.mmd` | Main allocation process flow |
| `availability_check.mmd` | Resource availability window check logic |

### System Design Diagrams
| File | Description |
|------|-------------|
| `system_architecture.mmd` | Overall system architecture with layers |
| `layered_architecture.mmd` | Detailed layered architecture |
| `database_schema.mmd` | Entity-Relationship diagram |
| `api_routes.mmd` | API endpoint structure |

### Policy & Placeholder Diagrams
| File | Description |
|------|-------------|
| `policy_system.mmd` | Policy system architecture |
| `placeholder_lifecycle.mmd` | Placeholder resource lifecycle |
| `capacity_tiers.mmd` | Capacity tier system |
| `user_workflow.mmd` | End-to-end user workflow |

### Sequence Diagrams
| File | Description |
|------|-------------|
| `seq_resource_creation.mmd` | Resource creation with availability validation |
| `seq_allocation_execute.mmd` | Execute allocation full flow |
| `seq_placeholder_convert.mmd` | Convert placeholder to actual resource |
| `seq_placeholder_batch.mmd` | Batch create placeholders |
| `seq_policy_update.mmd` | Update policy setting |

## How to View

### Option 1: Mermaid Live Editor
1. Go to [Mermaid Live Editor](https://mermaid.live/)
2. Copy the content of any .mmd file
3. Paste into the editor to see the rendered diagram

### Option 2: VS Code Extension
1. Install "Mermaid Markdown Syntax Highlighting" extension
2. Install "Markdown Preview Mermaid Support" extension
3. Open .mmd file and use preview

### Option 3: GitHub
GitHub automatically renders Mermaid diagrams in markdown files. Create a .md file with:
```markdown
```mermaid
<paste diagram content here>
```
```

### Option 4: Export to PNG/SVG
Use the Mermaid CLI:
```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i diagram.mmd -o diagram.png
```

## Diagram Categories

```
docs/diagrams/
├── Data Flow
│   ├── data_flow.mmd
│   ├── capacity_calculation.mmd
│   ├── report_generation.mmd
│   └── data_migration.mmd
├── Allocation
│   ├── allocation_process.mmd
│   └── availability_check.mmd
├── System Design
│   ├── system_architecture.mmd
│   ├── layered_architecture.mmd
│   ├── database_schema.mmd
│   └── api_routes.mmd
├── Policy & Placeholder
│   ├── policy_system.mmd
│   ├── placeholder_lifecycle.mmd
│   ├── capacity_tiers.mmd
│   └── user_workflow.mmd
└── Sequences
    ├── seq_resource_creation.mmd
    ├── seq_allocation_execute.mmd
    ├── seq_placeholder_convert.mmd
    ├── seq_placeholder_batch.mmd
    └── seq_policy_update.mmd
```

---
*Version: 1.0*
*Created: 2026-02-18*
