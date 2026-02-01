# README Redesign

**Date:** 2026-02-01
**Status:** Implemented

## Goals

Make the README accessible to all audiences:
- Researchers/Academics studying AAS/Industry 4.0
- Industrial practitioners implementing digital twins
- Developers building AAS tooling

## Design Decisions

### Approach: Hero + Pathways

Selected over alternatives (Quick Start Matrix, Accordion-style) because:
- Scannable structure lets users self-select their path
- Mermaid diagrams provide visual clarity
- Balances accessibility with technical depth

### Tone

Mixed approach:
- Friendly, welcoming intro section
- Professional, concise technical sections

### Visual Style

Mermaid diagrams for workflows (renders natively on GitHub)

## Structure

1. **Hero** - Value proposition, badges, main CTA
2. **Choose Your Path** - Three pathways with flowcharts
   - Find AASX files → Website
   - Contribute sources → SOURCES.yml workflow
   - Use the data → Download/API
3. **Contributing Sources** - Step-by-step with detailed flowchart
4. **Download the Data** - Formats table, code examples
5. **Technical Details** - Verification pipeline, safety measures
6. **Footer** - License, acknowledgments, links

## Implementation

- Commit: `docs: redesign README with user-friendly workflows`
- All sections use Mermaid flowcharts
- Dynamic badges pull from stats.json
