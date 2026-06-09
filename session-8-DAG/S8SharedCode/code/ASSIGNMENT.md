# parallel fan out example:
1.Find current GenAI job opportunities in:
- Bangalore
- Hyderabad
- Pune
and compare salaries.

# fail, recovery of DAG
"Generate a raw JSON array containing three separate objects representing these elements: Hydrogen, Helium, and Lithium. Each object must have keys for 'element' and 'atomic_number'. The entire raw text output block must contain exactly zero spaces and zero newline characters—it must be a single, completely unbroken string of text. Check the formatting of the resulting code string; if a single space or newline character is found anywhere inside the block, the data must be rejected as invalid, and the text must be refactored from scratch."

or
"List all countries that physically share a direct land border with France. Do not count overseas territories, islands, or non-contiguous land masses—only include nations on the main European continent. Run an inquiry to compile the list. The resulting list must be verified against a strict European map check; if any South American nations or island territories are accidentally included, the list must be failed, discarded, and rewritten to contain only European borders."

# coder
"A stock price starts at $100. Every day, it has a 52% chance of going up by 1% and a 48% chance of going down by 1%. Run a Monte Carlo simulation with 10,000 iterations to predict the expected value of the stock after 365 days. Set a random seed of 42 for reproducibility, and print only the final expected value rounded to two decimal places."

# graph_visualizer
added a new skill "graph_visualizer" which will visualize the DAG and save it as a png file.