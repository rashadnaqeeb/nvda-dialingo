# Dialingo

This is an addon that aims to detect languages even when they are not correctly tagged. It's mainly intended for bilingual people and language learners. Its main feature is the ability to detect when language changes, even within a sentence. This is especially useful for example if you text half in one language and half in another. There are limitations, explained below.

The addon detects languages in 3 ways:

1. Language tags in documents and web pages, when they're properly applied. This is what language switching addons have done for years.
2. Script changes, so for example the change from English, which uses Latin script, to Arabic, which uses the Arabic alphabet. Also reasonably common, also pretty much foolproof.
3. When no language tag is provided, and the text is in a single written script, the addon guesses the language of each sentence clause it reads. A sentence clause is any sentence fragment that's separated by punctuation.

The guessing uses a little language model, along with the Windows spellcheck dictionaries to decide how confident it is. When it's unsure, it errs on the side of caution and sticks with your default language.

You need NVDA 2026.1 or later.

## How to set it up

Go to the NVDA settings and scroll down to the Dialingo settings. Tab to Add, then go through and add each language you speak. These are the languages the model will try and match against. The more same-script languages you add, the worse the results get, so I'd suggest limiting it to languages you actually speak. Your default language, the language NVDA is set to, doesn't need adding.

When adding a language, the addon checks if you have the Windows dictionary for that language. If you don't, it offers to install it for you, which significantly increases accuracy. Windows will ask for administrator permission. The install runs in a PowerShell window, which can take 5-10 minutes. The addon will let you know when the download is done. If Windows doesn't pick up the dictionary straight away, it will ask you to restart Windows.

Each language gets its own synth, voice, speech rate, punctuation, and dictionary settings. If you give a language a different synth from your usual one, NVDA's synthesizer will show as "Language table" from then on. This is because the addon preloads all the synths you will be using to facilitate quick switching. If you switch back to your usual synth, the other synths stop being used until you go back to Language table.

If the addon finds a language you haven't added and your synth can't speak, say Arabic while you're using Eloquence, it uses the Windows OneCore voice for that language if you have one installed. There's a checkbox in the settings to turn this off.

## The synth settings ring

You can use the NVDA synth settings ring: NVDA+Control+left and right arrows, or NVDA+Shift+Control on the laptop layout. Move to the language lock setting, change the language, adjust the settings for that language, then move the lock back to automatic. Locking a language makes everything read in the voice you've selected for that language, but doesn't actually change NVDA's language. It works really similarly to the VoiceOver language rotor if you've ever used it.

Right after the lock is a detection setting. When the lock is set to automatic, it changes the detection setting of the entire addon, so you can turn language switching off globally if it's being buggy in a specific context. When a language is locked, it turns detection on or off for just that language.

## If it switches when it shouldn't

The settings have 3 detection modes. Full is the default and does everything above. Script and tags only never guesses, so it only uses methods 1 and 2. Off turns language switching off completely.

There's also a Strict checkbox, which makes Windows' own language detection agree before the addon switches. It switches less often, but it's very rarely wrong.

## Reporting problems

I want to hear about the addon switching when it shouldn't, not switching when it should, breaking with random synths I didn't test with, etc. If a particular line of text causes it issues, copying the line into the report would be awesome. Report issues on GitHub: https://github.com/rashadnaqeeb/nvda-dialingo/issues

If you're interested in the technical details of how this works, you can read the Claude-written readme on GitHub.

## License

The addon is GPL 2, like NVDA. The language model is derived from fastText's lid.176 model, under Creative Commons Attribution-Share-Alike 3.0.
