# Plan for Implementing AgentRegistry

## Goal

* Dynamically load agents from `.agent.md` files, parsing their fields and creating instances of `SimpleAgent`.
* Allow users to manually add custom agents implemented in source code, enabling flexibility for special use cases.
* Provide methods to retrieve agents by name and manage the registry.

## Current State

* **Agent Interface**:
  * The `Agent` class is defined in `quack_norris/agents/agent_registry.py`.
  * It serves as a base class for agents, with methods like `chat` and `fill_tool_description` that need to be implemented by subclasses.

* **SimpleAgent Implementation**:
  * The `SimpleAgent` class is defined in `quack_norris/agents/simple_agent.py`.
  - It extends the `Agent` class and provides functionality for loading agents from `.agent.md` files.

## Plan

* [x] Move the `Agent` Class:
  * File: `quack_norris/agents/agent_registry.py`
  * Move the `Agent` class from `agent.py` to `agent_registry.py`.
  * Ensure the `Agent` class serves as a base interface with abstract methods like:
    * `chat`: Handles the agent's interaction logic.
    * `fill_tool_description`: Provides a description of the agent's tools.
  * Define the required fields (`name`, `description`, `system_prompt`, `tools`, `model`, `skills`) as part of the interface.

* [x] Move the `SimpleAgent` Class:
  * File: `quack_norris/agents/simple_agent.py`
  * Move the `SimpleAgent` class from `agent.py` to `simple_agent.py`.
  * Ensure it imports the `Agent` class from `agent_registry.py`.

* [x] Implement the `AgentRegistry` Class:
  * File: `quack_norris/agents/agent_registry.py`
  * Add the `AgentRegistry` class to manage agents.
  * Initialize the registry with:
    * A directory path for `.agent.md` files.
    * An empty dictionary to store agents.
  * Implement methods to:
    * Load agents from `.agent.md` files.
    * Parse metadata and content from the files.
    * Initialize instances of `SimpleAgent` for agents loaded from `.agent.md` files.
    * Add, update, or remove agents in the registry based on file changes.
    * Allow users to manually add custom agents implemented in source code.

* [x] Set Up File Watching:
  * File: `quack_norris/agents/agent_registry.py`
  * Use `watchdog` to monitor the agent directory.
  * Handle file creation, modification, and deletion events to keep the registry up-to-date.

* [x] Provide Retrieval and Management Methods:
  * File: `quack_norris/agents/agent_registry.py`
  * Implement methods to:
    * Retrieve an agent by name.
    * List all agents in the registry.
    * Add custom agents programmatically.

* [ ] Testing and Validation:
  * File: `quack_norris/tests/test_agent_registry.py` (new file)
  * Write unit tests to ensure the `AgentRegistry` behaves as expected.
  * Test file watching functionality to verify that the registry updates correctly.
  * Test the integration of custom agents added programmatically.

* [ ] Documentation:
  * File: `docs/PLAN-agent-registry.md`
  * Document the `AgentRegistry` class and its methods.
  * Provide examples of how to use the registry, including adding custom agents.

## Acceptance Criteria

* [x] The `Agent` class is moved to `agent_registry.py` and refactored as an interface with abstract methods and required fields.
* [x] The `SimpleAgent` class is moved to `simple_agent.py` and implements the `Agent` interface.
* [x] The `AgentRegistry` class is implemented with methods for loading, retrieving, and managing agents.
* [x] Agents loaded from `.agent.md` files initialize instances of `SimpleAgent`.
* [-] The registry dynamically updates when `.agent.md` files are created, modified, or deleted.
* [x] Users can manually add custom agents implemented in source code.
* [ ] Unit tests are written and pass successfully.
* [ ] The implementation is documented, including usage examples.