# Graphify-Labs/graphify

- Website: https://graphify.com/
- Documentation: https://docs.graphify.com/open-source/cli-quickstart
- Business type: developer API
- Source: github-developer-tools (https://github.com/Graphify-Labs/graphify)
- Lead score: **65/100** - 50 base; +0 docs scored 7/10; +5 team inbox or phone; +10 developer product, docs drive adoption

## Summary

The Graphify documentation provides clear, step-by-step CLI quickstart guides and thorough MCP server setup instructions, including Docker usage. It is well-structured with consistent navigation and troubleshooting tips. However, it lacks a comprehensive API reference and detailed error code explanations. Some commands and flags are insufficiently explained, and the distinction between similarly named packages may confuse users. Additionally, the documentation assumes prior knowledge of advanced concepts like MCP and agents without introductory context, which could hinder new users.

## Documentation scores

| Dimension | Score | Why |
|---|---|---|
| Quality | 8/10 | The documentation is generally clear with well-structured step-by-step instructions, concrete CLI commands, and example outputs, especially in the CLI quickstart and MCP server quickstart pages. However, some commands and flags could use more explanation for novices, and the distinction between 'graphify' and 'graphifyy' packages might confuse users. |
| Completeness | 7/10 | The docs cover installation, quickstarts for CLI and skill usage, MCP server setup including Docker, and advanced usage like vibe coding. However, there is no detailed API reference or error code explanations beyond a brief troubleshooting table. Some advanced features like local Ollama backend or incremental updates are mentioned but not deeply documented in the sample. |
| Usability | 7/10 | The docs have a sidebar TOC, search, and consistent navigation. The pages are well segmented with headings and code blocks. However, the large number of commands and options might overwhelm new users. Some pages assume familiarity with concepts like MCP, LLM, or agents without introductory context. The presence of multiple installation methods and package names could cause confusion. |
| **Overall** | **7/10** | developer API guide with CLI and server setup |

### Strengths

- Clear step-by-step CLI quickstart with example commands and outputs
- Good coverage of installation and MCP server setup including Docker
- Includes troubleshooting tips and next steps guidance
- Documentation is well structured with headings and sidebar navigation

### Weaknesses

- No comprehensive API reference or detailed error code documentation
- Some commands and flags lack detailed explanation or examples
- Potential confusion around package naming ('graphify' vs 'graphifyy')
- Assumes familiarity with advanced concepts like MCP and agents without introductory context

### Missing sections

- Detailed API reference
- Comprehensive error codes and troubleshooting guide
- Examples of common use cases beyond quickstarts
- Glossary or explanation of key concepts like MCP, LLM, agents

## Recommended improvements

1. **[high] API Reference**: No comprehensive API reference is provided, limiting developers' ability to understand all available endpoints and parameters. -> Develop a detailed API reference section covering all endpoints, parameters, request/response formats, and examples.
2. **[high] Error Handling Documentation**: Error codes and troubleshooting guidance are minimal and not comprehensive. -> Expand the troubleshooting section to include detailed error codes, their meanings, and suggested resolutions.
3. **[medium] Command and Flag Explanations**: Some CLI commands and flags lack detailed explanations or usage examples, which may confuse novice users. -> Enhance command documentation with clear descriptions, examples, and use cases for each flag and command.
4. **[medium] Package Naming Clarity**: The similarity between 'graphify' and 'graphifyy' package names causes potential confusion. -> Clarify the differences between these packages early in the documentation and consider renaming or highlighting distinctions more prominently.
5. **[medium] Introductory Context for Advanced Concepts**: Documentation assumes familiarity with concepts like MCP, LLM, and agents without providing definitions or background. -> Add a glossary or introductory section explaining key concepts and terminology to support new users.
6. **[low] Use Case Examples**: Beyond quickstarts, there are few examples demonstrating common or advanced use cases. -> Include more practical examples and tutorials showcasing typical workflows and integrations.

## Contacts

- founders@graphify.com
- careers@graphify.com

## Outreach opener

**Subject:** Observations on Graphify's CLI Quickstart and Package Naming in Your Docs

I recently reviewed the Graphify documentation and noticed the CLI quickstart guides are well-structured with clear commands and example outputs, which is great for getting started. However, I also saw that the similarity between the 'graphify' and 'graphifyy' package names might cause confusion for new users. Additionally, some commands and flags could benefit from more detailed explanations to help novices. If you're interested, I have some ideas on how to make these areas clearer and more user-friendly.

## Evidence

- Doc discovery score 12: +2 code_blocks (12); +1 many_code_blocks; +2 install_command; +1 doc_headings (configuration); +2 doc_url; +3 doc_platform (mintlify); +1 sidebar_toc
- Pages sampled: 8, code blocks: 62, languages: none detected, search: True
  - CLI quickstart: build and query a code graph - Graphify: https://docs.graphify.com/open-source/cli-quickstart
  - Graphify CLI: open-source code knowledge graph - Graphify: https://docs.graphify.com/open-source/overview
  - Quickstart: map a repository with the skill - Graphify: https://docs.graphify.com/open-source/quickstart
  - Install Graphify CLI with uv or pipx - Graphify: https://docs.graphify.com/open-source/installation
  - MCP server quickstart: serve your graph - Graphify: https://docs.graphify.com/open-source/mcp-server
  - Self-host the Graphify MCP server with Docker - Graphify: https://docs.graphify.com/open-source/self-host
  - Vibe coding with Graphify CLI - Graphify: https://docs.graphify.com/open-source/vibe-coding
  - Run Graphify locally - Graphify: https://docs.graphify.com/open-source/local-development
