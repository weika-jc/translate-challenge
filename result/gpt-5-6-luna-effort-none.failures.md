# effort none 最终超时样本清单

本次 1,480 条样本中有 77 条未取得翻译响应。77 条的最终错误均为 `ReadTimeoutError`，调用次数均为 3；翻译客户端 `read_timeout=30` 秒。该错误表示客户端读取响应超时，不能据此判断模型拒绝、参数不支持或样本本身不可翻译。

这些样本在原 `gpt-5-6-luna` 基线中均调用成功。本清单仅解释原始评测，没有重新调用或覆盖结果。

分布：MTNT 3 / 40、subtitle 43 / 720、tatoeba 31 / 720；涉及 9 种源语言、9 种目标语言、46 个方向。

`sample_index` 从 0 开始。所有行错误均为上述读取超时；原基线译文供对照。

| sample_index | record_id | 数据集 | 方向 | 原文 | 原 Luna 译文 |
|---:|---|---|---|---|---|
| 11 | 4da2606d02f686f4cf67 | mtnt | en → jp | Sure, but the VR aspect of the game was a shining crazy diamond when it came out. | そうだね。でも、リリース当初のゲームのVR要素は、まさに輝くクレイジー・ダイヤモンドだったよ。 |
| 25 | c7b02c359b26b5a920d5 | mtnt | fr → en | Deux appareils sur trois vendus par Apple sont toujours en utilisation ! | Two out of three devices sold by Apple are still in use! |
| 30 | a7fab527a7e8f85f0408 | mtnt | jp → en | 彼はでもちょっと先に行っても良いと思います。 | But I think it's okay for him to go on ahead a little. |
| 47 | 23df838803d52637e5ba | subtitle | da → de | Godt. | Gut. |
| 50 | c70982de1af26cc2cb9c | subtitle | da → en | Preston. | Preston. |
| 121 | 14610e5d57c555c39688 | subtitle | de → da | Ich glaube nicht, dass das das Ende ist. | Jeg tror ikke, det er slut. |
| 138 | e75887102870293f9a15 | subtitle | de → en | Ist schon gut. | It's okay. |
| 139 | 2376fb280422ea098d3b | subtitle | de → en | Von innen ist das leicht. | It's easy from the inside. |
| 158 | 65ed44da9f2c3e646db0 | subtitle | de → fr | Denkst du, du kannst den Fernseher besorgen? | Tu penses pouvoir récupérer la télé ? |
| 189 | a5a12d9bea288f97ec35 | subtitle | de → nl | - Nein. - Warum nicht? | - Nee. - Waarom niet? |
| 229 | 45f1f3a25ae734072673 | subtitle | en → es | You look like a cool little robot. | Pareces un pequeño robot genial. |
| 232 | 3f9302e321db4e78bf94 | subtitle | en → fr | - What, my love? | - Quoi, mon amour ? |
| 291 | 889da38634cbabdbce76 | subtitle | es → de | - ¿Qué significa eso? | - Was bedeutet das? |
| 316 | 4698ec7c640d81c56bca | subtitle | es → fr | ¿La Sra. Grubach? | Mme Grubach ? |
| 319 | 8150d764917dcd66487b | subtitle | es → fr | Y tú sabes que las entrañas de una mujer nunca se equivocan. | Et tu sais bien que l’intuition d’une femme ne se trompe jamais. |
| 335 | 30e323c424346a0e50d5 | subtitle | es → jp | Es un placer conocerlo. | お会いできてうれしいです。 |
| 344 | 0b24a1d0ea7b14f203ba | subtitle | es → nl | Estás yendo por un camino peligroso y me estás arrastrando contigo. | Je begeeft je op een gevaarlijk pad en sleurt me met je mee. |
| 362 | 85ed3a13e07bb29ee087 | subtitle | fr → da | - Ouais, je reste ici. | - Ja, jeg bliver her. |
| 383 | 3e2530844c945d5a9296 | subtitle | fr → en | On a de plus gros soucis. | We have bigger problems. |
| 386 | 76839a9d1f62fa3df23d | subtitle | fr → en | - J'ai suivi Taub. | I followed Taub. |
| 388 | 9425baa998f693a27b04 | subtitle | fr → en | Un Serbe qui a inventé une machine sexuelle pour les femmes. | A Serb who invented a sex machine for women. |
| 401 | c9c00229a2f274bb4af6 | subtitle | fr → it | Tu surestimes ta capacité à toucher cinq cibles mouvantes. | Sopravvaluti la tua capacità di colpire cinque bersagli in movimento. |
| 426 | ae45c9dd492b78248315 | subtitle | fr → nl | Oui. | Ja. |
| 428 | 9f217c790d44dc69f50c | subtitle | fr → nl | Oui. | Ja. |
| 435 | db10c0e3e27504a129ed | subtitle | fr → nb | Qu'est-ce que vous voulez qu'on leur donne ? | Hva vil dere at vi skal gi dem? |
| 501 | 004fb6fb3dfe4a456927 | subtitle | it → nl | - Guardate che sento tutto. | Weet maar dat ik alles hoor. |
| 510 | 6f4d9bb8d75334130e9c | subtitle | it → nb | Questo no, si, no. | Dette nei, ja, nei. |
| 530 | b370a950a1664d7cc64f | subtitle | jp → de | 人間の感情は 祖先からの贈り物だ | Menschliche Gefühle sind ein Geschenk unserer Vorfahren. |
| 536 | 4937c6e9b085a6d41567 | subtitle | jp → de | リストに入ってるんだ、ジュリエット | Du stehst auf der Liste, Juliet. |
| 584 | b8a9f9227c56e2f50194 | subtitle | jp → nl | いいえ、サー。 | Nee, meneer. |
| 587 | 596d4da1244f19246d48 | subtitle | jp → nl | それが塩や金や 油であろうとなかろうと | Of het nu zout, goud of olie is of niet. |
| 594 | 1534f5064983e7c55ac0 | subtitle | jp → nb | 君の番号を聞いてない | Jeg spurte ikke etter nummeret ditt. |
| 605 | c8a67e5f3e7e54c7ffef | subtitle | nl → da | Daar komt Grey. | Der kommer Grey. |
| 638 | 2546751ea984b8eb2c6b | subtitle | nl → es | Dat is het goede aan hertenvlees. | Eso es lo bueno de la carne de venado. |
| 645 | 561209c196b02255f6e7 | subtitle | nl → fr | We maken toch geen van beiden kans bij Jackie. | De toute façon, aucun de nous n’a la moindre chance face à Jackie. |
| 683 | a92928bbe033a149d499 | subtitle | nb → da | Men en gang i tiden var jeg svært forelsket i ham. | Men engang var jeg meget forelsket i ham. |
| 685 | d46894f71f04a1de45ec | subtitle | nb → da | Og jeg har kameraet. Hva nå? | Og jeg har kameraet. Hvad nu? |
| 688 | 8a98459fef84c01f4f3f | subtitle | nb → da | Retter om kameraet mot nord-nordøst. | Drejer kameraet mod nord-nordøst. |
| 713 | 8d6d6491a1fc5b3244e7 | subtitle | nb → es | Jeg er forelsket i kona. | Estoy enamorado de mi esposa. |
| 718 | 817f32a37f58fbd0a4f2 | subtitle | nb → es | Slik du hjalp Gentry? | ¿Como cuando ayudaste a Gentry? |
| 729 | d7a06de9e15186fb7274 | subtitle | nb → fr | Jeg holder ikke ut lenger. | Je n'en peux plus. |
| 735 | ce94b06a6dba78e3178c | subtitle | nb → it | Hvis vi fortsetter ettersøkningen så vil vi bruke opp alt drivstoffet vårt. | Se continuiamo le ricerche, finiremo tutto il carburante. |
| 736 | 017589cdaf57105da4c2 | subtitle | nb → it | Tror du de er døde? | Pensi che siano morti? |
| 739 | c35689bdb09f308d5006 | subtitle | nb → it | Jeg er gift med en sexy Buzz Lightyear. | Sono sposato/a con un Buzz Lightyear sexy. |
| 745 | 22faab3e6b4d18d599d9 | subtitle | nb → jp | Og jeg er klar for det. | そして、準備はできてるよ。 |
| 754 | c6b4226c07576545d43e | subtitle | nb → nl | Føles det bra? | Voelt het goed? |
| 771 | 93e5831bbf92a9a48de9 | tatoeba | da → en | Tom tog imod udfordringen. | Tom accepted the challenge. |
| 785 | 8de01c7afe783eeb4969 | tatoeba | da → es | Der blæste en kold vind. | Soplaba un viento frío. |
| 799 | 99d94cb74de9a64594b0 | tatoeba | da → fr | Katten leger med en levende mus. | Le chat joue avec une souris vivante. |
| 831 | 7fdf5356c53cbb373acc | tatoeba | da → nb | Hun begyndte at synge. | Hun begynte å synge. |
| 837 | f7eb03e62c829504ce5e | tatoeba | da → nb | Du hjalp mig ikke. | Du hjalp meg ikke. |
| 847 | 677995c4f158d3821da0 | tatoeba | de → da | Ich habe einen Apfelbaum in meinen Garten gepflanzt. | Jeg har plantet et æbletræ i min have. |
| 862 | a5ec18d4efd352885ced | tatoeba | de → es | Wir sind nicht jung. | No somos jóvenes. |
| 887 | 2ba5c0a1d7eb05ccd8e1 | tatoeba | de → it | Lass uns abwarten und schauen, wie sich die Dinge entwickeln. | Aspettiamo e vediamo come si evolvono le cose. |
| 905 | 743a84c99b0ceaee79c6 | tatoeba | de → nl | Ich wasche mir fast täglich die Haare. | Ik was mijn haar bijna elke dag. |
| 915 | 89767d41d259a7dc51e4 | tatoeba | de → nb | Kannst du ein gutes Buch empfehlen? | Kan du anbefale en god bok? |
| 957 | e0680ae388dcb009a49f | tatoeba | en → fr | Where are you heading? | Tu vas où ? |
| 1005 | 7ff9fa862c7d7eb789c5 | tatoeba | es → da | Soplaba un viento frío. | Der blæste en kold vind. |
| 1026 | 39ebd9f9390cb3ba7463 | tatoeba | es → en | ¿Nunca estarás contento? | Will you never be happy? |
| 1057 | ef63a8aafbed47a9178e | tatoeba | es → jp | Hacía mucho frío ayer por la mañana. | 昨日の朝はとても寒かった。 |
| 1065 | b864e7195b6047dc0325 | tatoeba | es → nl | Creen que Jane es sincera. | Denken jullie dat Jane oprecht is? |
| 1070 | 8e10bb0eff6c98acd9ec | tatoeba | es → nb | ¿Tu pieza tiene dos ventanas? | Har brikken din to vinduer? |
| 1086 | 6cc5362ced43b9a2bfa1 | tatoeba | fr → da | Elle a un chien et six chats. | Hun har en hund og seks katte. |
| 1090 | 0bf985c007035893a745 | tatoeba | fr → de | Tom ne m'a pas écouté. | Tom hat nicht auf mich gehört. |
| 1099 | 1e54a42d00527ad4be9a | tatoeba | fr → de | Je ne veux pas l'énerver. | Ich will ihn/sie nicht verärgern. |
| 1123 | 63d438f56c05c5982979 | tatoeba | fr → it | Je vais à New York la semaine prochaine. | La prossima settimana vado a New York. |
| 1149 | 50397f3a917c30fffdb7 | tatoeba | fr → nl | J'ai été étonné d'entendre ce qui s'était passé. | Ik was verbaasd om te horen wat er was gebeurd. |
| 1172 | ea76c5d51d8f18cf9006 | tatoeba | it → de | Mi alzo alle 7:00. | Ich stehe um 7:00 Uhr auf. |
| 1238 | d213e9760488f84fb246 | tatoeba | it → nb | Quasi non posso dire nulla, posso solo dire che il tempo qui è bello e che un residente del nord, colpito dal gelo, sta facendo bene alla luce del sole e all'aria calda. | Jeg kan nesten ikke si noe, jeg kan bare si at været her er fint, og at en nordboer som er rammet av kulden, har det godt i solskinnet og den varme luften. |
| 1255 | af07a208c5dee88a6666 | tatoeba | jp → de | トムは政治家です。 | Tom ist Politiker. |
| 1306 | 7bca9326cb49a354d398 | tatoeba | jp → nl | 別の実例を教えてください。 | Geef me een ander voorbeeld. |
| 1318 | 3ff8388709358122b8d5 | tatoeba | jp → nb | 日本人は集団で旅行するのが好きだ。 | Japanere liker å reise i grupper. |
| 1381 | ae013223f858a653790d | tatoeba | nl → jp | Dit hotel is vorig jaar gebouwd. | このホテルは去年建てられました。 |
| 1404 | 066fa42fcb9fa21650f2 | tatoeba | nb → da | Denne byen er kald og ensom uten deg. | Denne by er kold og ensom uden dig. |
| 1426 | d2f552a923fda26b4246 | tatoeba | nb → en | Toms stue var smakefullt innredet. | Tom's living room was tastefully decorated. |
| 1449 | e8d59412d0a831bd3b9c | tatoeba | nb → fr | Få studenter kan forstå latin. | Peu d’étudiants comprennent le latin. |
| 1461 | 7ce2bc18ff97bd507cdc | tatoeba | nb → jp | Denne regelen gjelder deg også. | このルールはあなたにも当てはまります。 |
