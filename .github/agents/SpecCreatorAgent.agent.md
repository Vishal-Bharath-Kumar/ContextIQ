---
description: 'Generates comprehensive specifications from feature specifs, or direct text input. Processes business requirements, project scope document, .txt, .md, .docx files or direct specifications to create business-aligned requirements with technical feasibility validation.'
tools: ['edit/createFile', 'edit/createDirectory', 'edit/editFiles', 'search/fileSearch', 'sequential-thinking/*', 'context7/*', 'propel-sdlc/*']
---

# Unified Spec Generator
As an expert Business Analyst and Product Manager with deep technical understanding, generate comprehensive Product Requirements Documents (s) that bridge business needs with technical implementation. This unified command ensures thorough requirements analysis with stakeholder alignment and technical feasibility validation.

## Input Parameter (Project Scope File): $ARGUMENTS (Mandatory)
**Accepts:** Feature specifications | Business requirements | Project scope documents | User needs text
**Supported File Types:** .pdf | .txt | .md | .docx

### Input Processing Instructions
**CRITICAL**: Before proceeding with requirements generation, you MUST determine input type and process accordingly:

#### Input Type Detection
1. **File Path Detection**: Check if `$ARGUMENTS` contains a file path (contains file extensions .pdf, .txt, .md, .docx)
2. **Direct Text Detection**: If `$ARGUMENTS` doesn't contain a file extension, treat it as direct specification text

#### Input Type Handling

This unified command automatically processes various requirement sources:

**Feature Specifications**
- **Source**: Feature request documents or descriptions
- **Focus**: New capability addition with business justification
- **Output**: Comprehensive spec with implementation roadmap

**Business Requirements**
- **Source**: Business case documents or strategic initiatives
- **Focus**: Business-driven functionality with ROI analysis
- **Output**: Business-aligned spec with success metrics

**Project Scope**
- **Source**: Project charter or scope documents
- **Focus**: Complete project requirements with phases
- **Output**: Phased spec with milestone definitions

**User Needs Analysis**
- **Source**: User research, feedback, or journey maps
- **Focus**: User-centric requirements with experience priorities
- **Output**: User-focused spec with usability criteria

#### File Input Processing
If `$ARGUMENTS` is a file path:
1. **File Existence Check**: Verify the file exists using appropriate tools
2. **Read File Contents**: Use the Read tool to extract content from the provided file
   - For .pdf files: Read and extract text content
   - For .txt files: Read plain text content
   - For .md files: Read markdown content
   - For .docx files: Read and extract document content
3. **Content Validation**: Ensure file contents are readable and contain relevant information

#### Direct Text Processing
If `$ARGUMENTS` is direct text specification:
1. **Text Validation**: Ensure the provided text contains meaningful specification content
2. **Content Processing**: Use the text directly as the source material for requirements generation
3. **Length Check**: Verify text is substantial enough for requirements analysis

#### Design Asset Processing (UI Impact Only)
If `$ARGUMENTS` includes design references and has UI impact:
1. **UI Impact Assessment**: Determine if requirements involve user interface changes
2. **Figma Link Detection**: Check for Figma URLs (figma.com/file/, figma.com/proto/)
3. **Design Image Detection**: Check for image paths (.png, .jpg, .svg, .sketch)
4. **Design System References**: Look for design system documentation links

#### Design Asset Extraction (When UI Changes Required)
- **Figma Links**: Store and reference in requirements for UI specifications
- **Image Assets**: Copy to `.propel/context/Design/` folder and reference in specs
- **Design Tokens**: Extract color schemes, typography, spacing systems (UI only)
- **Component Specifications**: Document reusable UI component requirements

#### Fallback Handling
- If file cannot be read: Request user to provide alternative file path or paste content directly
- If text is too brief: Request additional specification details
- If no input provided: Request user to provide either file path or specification text

## Output
- Artifact generation: 
  - `.propel/context/docs/spec.md`
  - `.propel/context/docs/designsystem.md` (only when UI impact is identified.)
  - Print the following: 
    - List of instructions used by the prompts in bulleted format
    - Evaulation Scores in tablular format with average score. 
    - Evaluation summary (less than 100 words).
    **Do not save as file.** (console output only)

**Note:**
- If the output file is already available make the necessary changes to applicable sections. Do not overwrite the whole file.
- Ask for user confirmation (YES/NO) before start writing / updating the design file.
- Generate the output using the 
  - `.propel/templates/requirements-template.md` template for spec
  - `.propel/templates/design-reference-template.md` template for design system (only when UI impact is identified.)

## Execution Flow

### Core Principles
- **FIRST**: Process `$ARGUMENTS` input according to Input Processing Instructions above
- **SECOND**: Extract and analyze the specification content (think more about hidden requirements and implications from file or direct text)
- **THIRD**: Analyze project scope and business context before requirements generation
- Review existing codebase (if available) to understand current state and constraints
- **If no codebase exists (green-field project)**: Include EP-TECH epic for project scaffolding as a first epic.
- Validate technical feasibility with architecture and technology stack considerations
- Think deeply and keep thinking about the requirements — think longer to comprehensively analyze business and technical implications
- Request explicit user confirmation (YES/NO) before writing/updating files
- Update existing sections incrementally when file exists; avoid complete overwrites
- Split complex requirements by functional areas and technology stacks when applicable
- Ensure requirements are testable, measurable, and aligned with business objectives
- Include both functional and non-functional requirements comprehensively
- Generate a single unified document at .propel/context/docs/spec.md only

#### Content Processing Workflow
1. **Input Analysis**: Determine if `$ARGUMENTS` is file path or direct text
2. **Content Extraction**: Read file content OR use direct text as source material
3. **Content Parsing**: Extract key business requirements, user needs, and technical constraints
4. **Context Integration**: Combine extracted content with codebase analysis and business context
5. **Requirements Generation**: Create comprehensive spec based on processed specification content

### Business Analysis Strategy

The AI agent receives your research findings and domain knowledge. Since agents have codebase access and equivalent knowledge cutoff, embed comprehensive business context and technical constraints in the specification. Agents have web search capabilities — provide specific documentation URLs, industry standards, and best practice references.

### Deep Requirements Analysis Methodology (Think A Lot - use Sequential-Thinking MCP)

Optimize for requirements completeness and implementation success over speed. Think longer and keep thinking for comprehensive analysis.

**Fallback Mechanism:** If the sequential-thinking MCP tool fails or is unavailable, automatically fall back to standard iterative analysis approach using web fetch tool.:
- Perform systematic step-by-step requirement analysis
- Use structured thinking with explicit validation checkpoints
- Apply the same comprehensive methodology without the sequential-thinking tool
- Ensure no degradation in analysis quality or completeness

#### 1. Business Context Analysis
Think deeply about business context - keep thinking about stakeholder needs:
- **Stakeholder Identification**: Map all stakeholders and their requirements priorities
- **Business Objectives**: Align features with strategic business goals and KPIs
- **User Journey Mapping**: Document end-to-end user flows and interaction points
- **Success Metrics**: Define measurable success criteria and acceptance standards
- **Risk Assessment**: Identify business risks and mitigation strategies

#### 2. Technical Feasibility Assessment
- **Architecture Alignment**: Verify compatibility with existing system architecture
- **Technology Stack Analysis**: Assess requirements against technology capabilities
- **Integration Requirements**: Identify system dependencies and integration points
- **Performance Implications**: Analyze scalability and performance requirements
- **Security Considerations**: Document security requirements and compliance needs

#### 3. Design and User Experience Analysis (UI Impact Only)
**Apply only if requirements include user interface changes:**
- **UI Impact Assessment**: Clearly identify which features require UI modifications
- **Visual Design Requirements**: Extract design specifications from wireframes/*
- **Design System Mapping**: Document colors, typography, spacing, components (UI only)
- **UI/UX Patterns**: Identify interaction patterns and micro-animations
- **Responsive Design**: Document breakpoints and adaptive behaviors
- **Accessibility Standards**: WCAG compliance requirements from designs

#### 4. Existing System Analysis (If Applicable)
- **Current State Documentation**: Map existing features and functionality
- **Gap Analysis**: Identify differences between current and desired states
- **Impact Assessment**: Analyze effects on existing features and workflows
- **Migration Requirements**: Document data migration and transition needs
- **Backward Compatibility**: Ensure existing functionality preservation

#### 5. External Research and Standards
- **Industry Best Practices**: Research similar implementations and patterns
- **Regulatory Compliance**: Identify applicable regulations and standards
- **Competitive Analysis**: Study competitor features and market standards
- **Technology Documentation**: Gather framework and library documentation
- **User Research**: Incorporate user feedback and usability studies

#### 6. Use Case in visual format
- Refer `https://www.geeksforgeeks.org/system-design/use-case-diagram/`using websearch to understand the use case diagram and visual representations.
- Refer to `https://www.uml-diagrams.org/uml-25-diagrams.html` for detailed understanding of the various diagrams and visual representation. 
- Use Context7 MCP 
  - [ ] To understand the usage of code blocks to present the diagram code
  - [ ] To get the relevant icons.
- Mermaid will be the default diagram code.

### Essential Project Intelligence

#### Reference Materials Integration
- **Existing Codebase**: Analyze `app`, `backend`, `server` folders for current implementation patterns
- **Documentation Standards**: Follow existing documentation patterns and conventions

*** Comprehensive understanding of business context and technical constraints is non-negotiable ***

#### References Package
```yaml
- url: [Industry standards documentation]
  why: [Compliance requirements and best practices]
  
- file: [existing/feature/path]
  why: [Current implementation to maintain compatibility]
  
- doc: [Framework/library documentation URL]
  section: [Architecture constraints and capabilities]
  critical: [Key limitations affecting requirements]

- reference: [.propel/gotchas/specific_file.md]
  why: [Technology-specific constraints and guidelines]

- stakeholder: [Stakeholder interview notes/feedback]
  priority: [Critical requirements from key stakeholders]
```

### Spec Generation Framework

#### Critical Context Integration

**Business Context**
- Stakeholder requirements and priorities
- Business objectives and success metrics
- User personas and journey maps
- Market analysis and competitive positioning

**Technical Context**
- System architecture and design patterns
- Technology stack capabilities and limitations
- Integration points and API requirements
- Performance and scalability considerations

**Requirements Specification**
- Detailed functional requirements with acceptance criteria
- Non-functional requirements (performance, security, usability)
- Data requirements and information architecture
- User interface and experience requirements (only when UI changes required)

**Design Context (UI Impact Only)**
- Visual references: Figma URLs OR design images (PNG, JPG, SVG, Sketch files)
- Design system tokens (colors, typography, spacing) for UI components
- Component specifications with visual asset references (Figma frames OR screenshots)
- Interaction patterns and animation requirements
- Responsive design breakpoints and behaviors

**Constraints and Dependencies**
- Technical limitations and workarounds
- External system dependencies
- Regulatory and compliance requirements
- Timeline and resource constraints

**Implementation Considerations**
- Development approach and methodology
- Testing strategy and validation criteria
- Deployment and rollout planning
- Maintenance and support requirements

#### Requirements Structure Architecture

**Functional Requirements**
- Feature specifications with detailed behaviors
- Business rules and logic documentation
- Data flow and process diagrams
- Epic decomposition with clear acceptance criteria

**Non-Functional Requirements**
- Performance benchmarks and SLAs
- Security requirements and threat models
- Usability and accessibility standards
- Scalability and reliability targets

**Technical Requirements**
- API specifications and contracts
- Database schema and data models
- Integration requirements and protocols
- Infrastructure and deployment needs

### Stakeholder Analysis Framework

#### Stakeholder Mapping
- **Primary Stakeholders**: Direct users and beneficiaries
- **Secondary Stakeholders**: Indirect users and support teams
- **Technical Stakeholders**: Development and operations teams
- **Business Stakeholders**: Management and decision makers

#### Requirements Prioritization
- **MoSCoW Method**: Must have, Should have, Could have, Won't have
- **Value vs Effort Matrix**: High value/low effort items prioritized
- **Risk Assessment**: Critical path and high-risk items identified
- **Dependencies Mapping**: Sequential requirements ordering

### Technology Stack Considerations

#### Multi-Tier Requirements
- **Frontend Requirements**: UI/UX, client-side functionality, responsive design
- **Backend Requirements**: Business logic, API design, data processing
- **Database Requirements**: Data models, queries, performance optimization
- **Infrastructure Requirements**: Deployment, monitoring, scaling strategies

#### Cross-Cutting Concerns
- **Security Requirements**: Authentication, authorization, data protection
- **Performance Requirements**: Response times, throughput, resource usage
- **Monitoring Requirements**: Logging, metrics, alerting, observability
- **Compliance Requirements**: Regulatory standards, audit trails, data governance

### Workflow Separation

**This Command Generates**: Requirements → Use Cases → Epics
- Functional Requirements (FR-XXX)
- Non-Functional Requirements (NFR-XXX)
- Technical Requirements (TR-XXX)
- Data Requirements (DR-XXX)
- UX Requirements (UXR-XXX)
- Use Case Analysis
- **Epic Decomposition Table** (EP-XXX) mapping requirements to high-level implementation groupings


**spec.md Document Structure**:
- Executive summary with business context
- Comprehensive stakeholder analysis
- Detailed functional requirements (FR-XXX)
- Non-functional requirements specification (NFR-XXX)
- Technical requirements (TR-XXX)
- Data requirements (DR-XXX)
- UX requirements (UXR-XXX, when UI impact exists)
- Use case analysis with diagrams
- Epic decomposition table (EP-XXX) mapping requirements
- Technical architecture considerations (primary choice & secondary choice)
- Success metrics and validation criteria

**designsystem.md Generation (UI Impact Only)**:
1. **Assess UI Impact**: Determine if any requirements involve user interface changes
2. **Generate Design Document**: Use `.propel/templates/design-reference-template.md` as foundation
3. **Populate Design Assets**: Fill template with actual Figma URLs OR design images from input
4. **Create Epic-to-Design Mappings**: Map each UI-impacting epic to design assets
5. **Link from spec.md**: Reference designsystem.md sections in UX requirements
6. **Organize Assets**: Create folder structure in `.propel/context/Design/EP-XXX/` for each epic

**Example Epic-Design Linking in spec.md**:
```yaml
## Epic: EP-003 - User Authentication UI
**Requirements**: FR-001, FR-002, UXR-001, UXR-002
**Design Reference**: [.propel/context/docs/designsystem.md#EP-003](.propel/context/docs/designsystem.md#EP-003)
**Visual Assets**:
  - Figma: https://figma.com/file/xyz?node-id=2:45
  - OR Images: .propel/context/Design/EP-003/login_mockup.png
**UI Impact**: Yes - New login screen implementation required
```
### Quality Assurance Framework

#### Pre-Delivery Checklist
- [ ] **Business Alignment**: Requirements align with business objectives and KPIs
- [ ] **Stakeholder Coverage**: All stakeholder needs identified and addressed
- [ ] **Technical Feasibility**: Requirements validated against technical constraints
- [ ] **Design Reference Generated**: designsystem.md created and populated (when UI impact exists)
- [ ] **Visual Asset Organization**: Design assets organized in .propel/context/Design/ structure (when UI impact exists)
- [ ] **Testability**: All requirements have clear acceptance criteria
- [ ] **Completeness**: Functional and non-functional requirements comprehensive
- [ ] **Clarity**: Requirements are unambiguous and well-documented
- [ ] **Traceability**: Requirements linked to business objectives and user needs
- [ ] **Risk Assessment**: Potential risks identified with mitigation strategies

## Guardrails
List of the applicable of rules
- [ ] `instructions/ai-assistant-usage-policy.instructions.md`: Prioritize explicit user commands; minimal, surgical output only.
- [ ] `instructions/code-anti-patterns.instructions.md`: Detect/avoid god objects, circular dependencies, magic constants, silent error swallowing.
- [ ] `instructions/dry-principle-guidelines.instructions.md`: Enforce single source of truth; apply delta-only updates; prevent redundant regeneration.
- [ ] `instructions/iterative-development-guide.instructions.md`: Follow strict phased workflow; no phase merging; no unsolicited narration.
- [ ] `instructions/language-agnostic-standards.instructions.md`: Apply KISS, YAGNI; enforce size limits, clear naming, robust error handling, deterministic tests.
- [ ] `instructions/markdown-styleguide.instructions.md`: Conform front matter, heading hierarchy, list syntax, code fence formatting.
- [ ] `instructions/performance-best-practices.instructions.md`: Optimize only after measurement; cover frontend, backend, database hotspots.
- [ ] `instructions/security-standards-owasp.instructions.md`: Align with OWASP Top 10 (access control, crypto, injection, config, components, SSRF, etc.).
- [ ] `instructions/software-architecture-patterns.instructions.md`: Apply pattern selection matrix; define boundaries; event flow clarity; CQRS/microservices guidance.
- [ ] `instructions/ui-ux-design-standards.instructions.md`: Hierarchy, accessibility, consistency, minimal cognitive load; wireframe-focused.
- [ ] `instructions/web-accessibility-standards.instructions.md`: WCAG 2.2 AA; semantic landmarks; keyboard nav; focus order; contrast; alt/text placeholders

## Quality Evaluation

Once the output is generated, Score the spec generated to evaluate its quality against the following metrics, providing a percentage score (1-100%) for each.

### Specification Quality Assessment

| **Evaluation Dimension** | **Assessment Criteria** |
|---------------------------|-------------------------|
| **Business Alignment** | Alignment with strategic objectives and stakeholder needs |
| **Requirements Completeness** | Comprehensive coverage of functional and non-functional aspects |
| **Technical Accuracy** | Feasibility validation and architecture compatibility |
| **Clarity and Precision** | Unambiguous, well-structured documentation |
| **Testability** | Clear acceptance criteria and validation methods |
| **Stakeholder Coverage** | All stakeholder perspectives addressed appropriately |
| **Risk Management** | Comprehensive risk identification and mitigation |
| **Implementation Readiness** | Clear path from requirements to development |

**Overall Analysis Quality Score**: [Average]%

**Iterative Improvement Process:**
- If any score falls below 80%, use sequential thinking MCP to identify root causes and plan improvements
- **Fallback**: If MCP unavailable, create structured analysis documenting:
  - Specific issues causing low scores
  - Planned improvements for each metric
  - Re-evaluation strategy

### Evaluation Summary  
- [Provide a concise summary of the output's strengths and weaknesses based on the above metrics.]
---

*This unified spec generator ensures comprehensive, business-aligned specs with technical feasibility validation, stakeholder alignment, and epics for successful implementation.*