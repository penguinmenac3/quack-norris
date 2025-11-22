# Plan to Restructure SimpleAgent to Support Skills

## Goal
Refactor the `SimpleAgent` class to support modular skills. Skills will be defined in separate `.skill.md` files and dynamically appended to the agent's system prompt. This will enable better modularity, reusability, and extensibility of agent capabilities.

## Current State

### Agent Class
- **Base Class**: `Agent` defines the basic structure for agents, including `name`, `description`, and abstract methods like `chat`.
- **SimpleAgent**: Implements the agent's workflow, tool management, and prompt logic in a monolithic design.
  - Loads metadata and prompts from `.agent.md` files.
  - Dynamically formats the `system_prompt` with placeholders (e.g., `{task}`, `{today}`).
  - Filters tools based on the `tools` list and namespace restrictions.
  - Sends requests to the LLM and processes responses, including tool calls.

### Limitations
- No support for modular skills.
- Skills cannot extend the agent's prompt or tools dynamically.
- The `SimpleAgent` combines multiple responsibilities, making it harder to extend or maintain.

## Plan

### 1. Define Skill Structure
- **Implementation Files**:
  - Define skills in `.skill.md` files stored alongside `.agent.md` files (e.g., in `~/.config/quack-norris/agents/`).
  - No code changes required for this step, but ensure the `.skill.md` files follow this structure:
    ```yaml
    ---
    name: skill_name
    description: A brief description of the skill.
    tools: tool1, tool2
    ---
    Skill-specific prompt goes here.
    ```
- **Status**: Completed

### 2. Implement a Skill Registry
- **Implementation Files**:
  - Create a new file: `quack_norris/agents/skill_registry.py`.
  - Implement the `SkillRegistry` class to:
    - Load skills from `.skill.md` files.
    - Cache loaded skills to avoid duplication in memory.
    - Provide methods to retrieve skills by name.
    - Monitor the skill directory for changes and reload modified skills dynamically.
- **Status**: Completed

### 3. Refactor SimpleAgent
- **Implementation Files**:
  - Modify `quack_norris/agents/agent.py`:
    - Add a `skills` attribute to store the list of skills the agent can use.
    - Use the `SkillRegistry` to load and manage skills.
    - Update the `chat` method to dynamically append the active skill's prompt to the `system_prompt`:
      ```
      system_prompt + "\n\n" + skill_prompt
      ```
    - Merge the agent's tools with the active skill's tools.
- **Status**: Completed

### 4. Update Metadata Parsing
- **Implementation Files**:
  - Modify `quack_norris/agents/agent.py`:
    - Extend `.agent.md` parsing to include a `skills` field:
      ```yaml
      ---
      name: agent_name
      description: A brief description of the agent.
      tools: tool1, tool2
      skills: skill1, skill2
      ---
      Agent-specific prompt goes here.
      ```
    - Use the `SkillRegistry` to load and validate the listed skills.
- **Status**: Completed

### 5. Ensure Backward Compatibility

- **Implementation Files**:
  - Modify `quack_norris/agents/agent.py`:
    - Ensure the `SimpleAgent` can function without skills if none are defined.

## Acceptance Criteria
- [ ] Skills are stored alongside `.agent.md` files.
- [ ] A `SkillRegistry` class is implemented to manage skills.
- [ ] The `SimpleAgent` class supports modular skills.
- [ ] Skills are defined in `.skill.md` files and dynamically loaded.
- [ ] The agent's system prompt includes the active skill's prompt.
- [ ] Tools from the active skill are merged with the agent's tools.
- [ ] A sample skill (`food-recommender.skill.md`) is implemented.
- [ ] Existing agents remain functional without modification.