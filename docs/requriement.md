
Lead Scraper: 
- Developers / owner of product - who has websites / products that reqruies a documentation
- Find out how good or bad is the documentation of their product
- any script or opener for them

1. go to wbsite like product hunts, etc - proper catregory if possible and then loop throuigh the list of products, and go into their website - you can use playwright if you want or something else. use python if possible you can also use selenium if needed
--- the flow will be like this
2. Detect using AI, whhether they have any documentation or not, if its work persuing, find doumentation
<only proceed if they have a documentation, otherwise skip the lead>
3. Collect emails and phone numbers by craling the entire website, and find the contact information of the developers or owners. - you can do it by usng regex, just crawl autmatically through pages and use regex to find emails and phone numbers
<only if they have a documentation, otherwise skip the lead either number or email>
4. use Ai to purify the collected emails and phone numbers, and remove any duplicates or invalid entries.
you can get the ai to rewrite / regenerate the email or phoen number list uisng sturtcured output.
5. Analyze the documentation for quality, completeness, and usability - use structred output
6. Generate a report or summary of the findings, highlighting areas for improvement - use structured output

Listing websites to start outr from:
https://github.com/topics/api
https://github.com/topics/developer-tools
https://www.producthunt.com/topics/developer-tools?order=recent_launches

lets only have these for now.
do not hardcode these urls, make them dynamic ar automation logic for each should also be dynamic so that we can add easily aniutyhing new in the future.

we will use a deterministic flow / approach. - HARDER TO DO !!

----------------

2. Detect using AI, whhether they have any documentation or not, if its work persuing, find doumentation

2.1 -- use Ai to detect whether its the kind of business in the first place which has a documentation or not !
check header for any text or word that means something related to the documentation like "docs", "documentation", "api", "developer", "manual", etc.

2.2 -- Actually find out the documentatipm page. 
I can go into each page and check if there is any code, or api ref or phrase that indicates that it is a documentation page. 
we can use REGEX to match common patterns.

once detcted we can easily do the step 4

---- Tech Stack for AI detection and analysis ----

- openaiAPI for AI detection and analysis of documentation quality
- langchain and langraph tools for building the AI detection and analysis pipeline

langchain gives you:
- AI model integration - cliant that can be used to easily integrate with OpenAI API
- Prompt templates - for creating prompts to send to the AI model

langraph gives you:
- Graph-based data structure for representing the documentation and its components

-----------------

(Node) ---- Edge ---- (Node) ---- Edge ---- (Node)

Node - Code snippet, any code will be here that you write, any logic, function
Edge - condtion, any condition that will be checked to move to next node, any logic that will be used to decide the next node

In our case:

Node:
(2.1) - Detect using AI, whether they have any documentation or not, if it's worth pursuing

Edge

Node:
(2.2) - Actually find out the documentation page using regex 

Conditional Edge:
- If documentation is found, proceed further to step 3

Node:
(3) - Collect emails and phone numbers by crawling the entire website, and find the contact information of the developers or owners.

Conditional Edge:
- If contact information is found, proceed to step 4

node: 
(4) - Use AI to purify the collected emails and phone numbers, and remove any duplicates or invalid entries.

node:
(5) - Analyze the documentation for quality, completeness, and usability using AI

Edge

Node:
(6) - Generate a report or summary of the findings, highlighting areas for improvement

-------

4. use Ai to purify the collected emails and phone numbers, and remove any duplicates or invalid entries.
you can get the ai to rewrite / regenerate the email or phoen number list uisng sturtcured output.

{
    "emails": [
        "example@example.com",
        "khasdkh@lkahsdljh.asd",
        "invalid-email@.com"
    ],
    "phone_numbers": [
        "+1-123-456-7890",
        "123-456-7890",
        "(111) 111-111",
    ]
}

prompt: "You are a helpful assistant. Please rewrite the following list of emails and phone numbers, removing any duplicates or invalid entries. Remove anything that you think is invalid or not a proper email or phone number. Please provide the output in a structured JSON format with two keys: 'emails' and 'phone_numbers'."

Schema for structured output:

pydandtic Schema:
```python

from pydantic import BaseModel, EmailStr, constr

class ContactInfo(BaseModel):
    emails: list[str]
    phone_numbers: list[str]  # Validates international phone numbers
```

Ai sample output:
```json
{
    "emails": [
        "example@example.com",
    ],
    "phone_numbers": [
        "+1-123-456-7890",
        "123-456-7890"
    ]
}
```











