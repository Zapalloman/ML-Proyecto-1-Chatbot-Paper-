# Model selection — Phase 0 F0.3

**Date**: 2026-05-06T13:12:09
**Platform**: Linux-7.0.3-arch1-2-x86_64-with-glibc2.43
**GPU**: NVIDIA GeForce GTX 1650 SUPER, 4096 MiB, 595.71.05
**Ollama**: 0.13.5

## Summary table

| Model | TTFT (s) median | Tok/s median | OK count |
|---|---|---|---|
| `gemma3:4b` | 0.31 | 32.4 | 5/5 |
| `qwen2.5:3b` | 0.19 | 76.7 | 5/5 |
| `gemma3:1b` | 0.23 | 131.5 | 5/5 |

## Detailed results

### `gemma3:4b`

**P1** ('Pikachu evolves into Raichu using a Thunder Stone. In one sentence, what type is Raichu?')  
_TTFT: 57.00s · 34.4 tok/s · 11 tokens · ok=True_  
```
Raichu is an Electric-type Pokémon.
```

**P2** ('Charizard tiene dos tipos. ¿Cuáles son? Responde en español en una frase.')  
_TTFT: 0.31s · 34.0 tok/s · 15 tokens · ok=True_  
```
Charizard es un Pokémon de tipo Fuego y Volador.
```

**P3** ('Between Mewtwo and Mew, which has higher base Special Attack? State the value.')  
_TTFT: 0.30s · 32.3 tok/s · 50 tokens · ok=True_  
```
Mewtwo has a higher base Special Attack.

*   **Mewtwo:** 155
*   **Mew:** 100

So, Mewtwo's base Special Attack is **155**.
```

**P4** ('Why is Cubone said to wear a skull on its head, according to Pokédex lore?')  
_TTFT: 0.33s · 31.5 tok/s · 374 tokens · ok=True_  
```
The reason Cubone wears a skull on its head is a deeply sad and poignant part of its lore, rooted in a tragic story of loss and mourning. Here's a breakdown of the explanation according to the Pokémon Pokédex lore:

* **The Death of Its Mother:** Cubone isn't born; it's actually the pup of a deceased Marrow Pokémon. Its mother was killed by a Rhyhorn while attempting to protect her young.

* **Collecting the Skull:** Overcome with grief, Cubone began collecting the skull of its mother. It wraps the skull around its head as a constant reminder of her loss and as a symbol of its unending mourning. 

* **Symbolic Representation:** The skull isn't just a random accessory. It represents Cubone's profound sadness, its inability to move on, and its desire to protect what little remains of its lost loved one.


**Key Points and Variations:**

* **Early Lore:** Originally, the lore was *much* more explicit and heartbreaking. The Pokédex entries were direct about the mother's death. However, over time, the lore was toned down somewhat to be less intensely graphic for younger audiences.

* **Evolution and Continuing Grief:** Cubone's evolution into Marowak reinforces this theme. Marowak’s power is said to come from its “unending grief” – a reflection of its unwavering mourning for its dead mother.


**In short, the skull is a symbol of grief and loss, a tangible representation of Cubone’s eternal mourning for the only parent it ever knew.**

You can find more detailed information on the official Pokémon website: [https://www.pokemon.com/pokemon-species/cubone/](https://www.pokemon.com/pokemon-species/cubone/)
```

**P5** ("Reply in Spanish: list three Eeveelutions and their types as 'Name: Type'.")  
_TTFT: 0.30s · 32.4 tok/s · 41 tokens · ok=True_  
```
Okay, here are three Eeveelutions and their types, as requested:

*   Vaporeon: Water
*   Jolteon: Electric
*   Flareon: Fire
```

### `qwen2.5:3b`

**P1** ('Pikachu evolves into Raichu using a Thunder Stone. In one sentence, what type is Raichu?')  
_TTFT: 19.00s · 83.5 tok/s · 9 tokens · ok=True_  
```
Raichu is of Electric type.
```

**P2** ('Charizard tiene dos tipos. ¿Cuáles son? Responde en español en una frase.')  
_TTFT: 0.19s · 81.2 tok/s · 11 tokens · ok=True_  
```
Charizard tiene los tipos fuego y lizard.
```

**P3** ('Between Mewtwo and Mew, which has higher base Special Attack? State the value.')  
_TTFT: 0.16s · 74.7 tok/s · 74 tokens · ok=True_  
```
Mewtwo has a higher base Special Attack stat compared to Mew.

The base Special Attack for Mew is 40.
The base Special Attack for Mewtwo varies depending on its form (standard or mega), but it typically ranges from 60 to 80, with the standard form having a slightly lower base value of 60.
```

**P4** ('Why is Cubone said to wear a skull on its head, according to Pokédex lore?')  
_TTFT: 0.19s · 73.9 tok/s · 213 tokens · ok=True_  
```
In Pokémon lore, Cubone is known for wearing what appears to be a skull-shaped mask or helmet on its head. This design is likely an artistic representation that gives the Pokémon a unique appearance and adds to its distinctive look.

The origin of this feature in the Pokémon universe can't be definitively traced back to any specific lore document or creator statement, as it is part of the visual design created by game developers, illustrators, and other artists. The skull-like helmet may symbolize Cubone's connection to death, decay, or its mysterious origins in the wilds.

Pokémon are creatures with a wide variety of appearances that are often influenced by real-world animals, mythical beasts, and human-made objects. The design choices for each Pokémon are made based on their characteristics, abilities, and place within the game world's lore and aesthetic.

So while we can't pinpoint a single reason or piece of official information stating why Cubone has this skull helmet, it is likely intended to be visually distinctive and add to its overall appeal and uniqueness in the Pokémon universe.
```

**P5** ("Reply in Spanish: list three Eeveelutions and their types as 'Name: Type'.")  
_TTFT: 0.16s · 76.7 tok/s · 23 tokens · ok=True_  
```
Nombre: Calyx: Psychic
Nombre: Solgaleo: Ghost
Nombre: Lunala: Fairy
```

### `gemma3:1b`

**P1** ('Pikachu evolves into Raichu using a Thunder Stone. In one sentence, what type is Raichu?')  
_TTFT: 30.11s · 125.5 tok/s · 16 tokens · ok=True_  
```
Raichu is a Thunderbolt Pokémon, known for its powerful lightning abilities.
```

**P2** ('Charizard tiene dos tipos. ¿Cuáles son? Responde en español en una frase.')  
_TTFT: 0.22s · 137.1 tok/s · 21 tokens · ok=True_  
```
Charizard tiene dos tipos, Firey y Dark, cada uno con sus propias características y habilidades.
```

**P3** ('Between Mewtwo and Mew, which has higher base Special Attack? State the value.')  
_TTFT: 0.22s · 132.2 tok/s · 58 tokens · ok=True_  
```
Mewtwo has a significantly higher base Special Attack than Mew.

*   **Mewtwo:** 1100
*   **Mew:** 600

Therefore, **Mewtwo** has a base Special Attack of 1100.
```

**P4** ('Why is Cubone said to wear a skull on its head, according to Pokédex lore?')  
_TTFT: 0.23s · 129.1 tok/s · 521 tokens · ok=True_  
```
You've stumbled upon a really fascinating and somewhat debated point! The reason Cubone is said to wear a skull on its head in Pokémon lore is rooted in a specific, and quite bizarre, legend about the Pokémon’s development. Here’s the breakdown:

**The Legend of the "Skull-Bearing" Cubone:**

* **The Origin:** The story began with a researcher named Dr. James G. (a name often associated with Pokémon lore) who was studying a rare, overgrown Pokémon. He noticed that Cubone seemed to have a distinct, almost melancholic, expression. 
* **The Observation:** Dr. G. observed that Cubone's head was perpetually covered in a fine, gray dust that resembled a skull. He hypothesized that this dust was somehow connected to his own experiences and memories, and that it represented a dormant, ancient sorrow.
* **The Transformation:**  He theorized that the dust was influencing Cubone’s growth, subtly shaping it into a spectral, almost mournful form.  He believed it was a manifestation of a dark past.

**What the Pokédex Says (and What's More Accurate):**

* **Official Pokédex Entry (as of 2018):**  "Cubone is said to be a Pokémon that carries a dark, somewhat melancholic history. Its head is covered in a fine gray dust, believed to be a manifestation of its past." This entry *does* state that the dust *could* be linked to a tragic past, but it doesn't explicitly say it’s a skull.

**Why the Confusion?**

* **Visual Similarity:** The appearance of the dust is strikingly similar to a skull, and it’s this visual similarity that led to the widespread belief in the legend.
* **The "Past" Element:** The legend heavily emphasizes the *feeling* of sadness and loss associated with Cubone.  The “skull” metaphor is a way to represent this emotional weight.

**Important Note:** This is a *legendary* story.  Pokémon lore has evolved, and the significance of the skull on Cubone's head has largely been dropped in later generations. It remains a charming, quirky detail that adds to the Pokémon's mystique.

**In short, the “skull” on Cubone is a visual metaphor for a deep, perhaps melancholic, past, rather than a literal representation of a skull.**

Do you have any other questions about Pokémon lore or the story behind Cubone?
```

**P5** ("Reply in Spanish: list three Eeveelutions and their types as 'Name: Type'.")  
_TTFT: 0.23s · 131.5 tok/s · 53 tokens · ok=True_  
```
¡Claro! Aquí tienes tres Eeveelutions con sus tipos:

*   Name: Lea
    Type: Planta

*   Name: Umbreon
    Type: Fire

*   Name: Sylveon
    Type: Fairy
```

---

## Verdict

**Selected**: _<fill in after reviewing answers above against the rubric in MODEL-SELECTION.md>_  
**Rationale**: _<fill in>_  
**Known weak points to carry into the test report**: _<fill in>_  