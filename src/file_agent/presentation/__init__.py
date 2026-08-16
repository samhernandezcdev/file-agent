"""Spanish (and future-language) product-messaging presentation layer
(FA-014). Strictly one-directional: this package depends on
file_agent.application/file_agent.domain for their enums/DTOs; nothing in
application/domain/destination/any engine ever imports file_agent.presentation.
It sits at the very top of the dependency graph, the last step before
terminal rendering -- messages are produced strictly after a decision is
already final and never feed back into authorization or control flow.
"""
