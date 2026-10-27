# Third-party material

## Station art (generated)

- What: every picture the web station (`clyde station web`) shows, in `src/agent/station_art/`: the seven crew (`clyde-*`, `bonnie-*`, `master-*`, `advisor-*`, `newsboy-*`, `mechanic-*`, `clerk-*`), the furniture (`furn-*`), the floors, walls and wall decorations (`tile-*`) and the sky and garden (`scene-*`).
- How: the maintainer generated them as sprite sheets with ChatGPT's image generation, from prompts written for this project (1930s, isometric pixel art, the people and the furniture named in the station's code). `tools/slice_crew.py`, `tools/slice_env.py` and `tools/build_env_art.py` cut the sheets into the single pictures: they remove the background and cut, nothing is repainted.
- Author and licence: no outside artist's work is used. The pictures are machine-generated output; the rights in such output depend on the generator's terms and local law. Before a public release, read OpenAI's current terms for the use of generated images and record the result here.
- Previously: the station used the "Cozy Space Station" sprites by Bramble & Byte (CC-BY 4.0). They are no longer in the repository.
- Credit: the station page's legend says the pictures were generated for this project.
