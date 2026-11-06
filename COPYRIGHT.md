# Autorska prava pesama (provera 6. 11. 2026.)

Pravilo koje koristimo: pesma je slobodna ako su i kompozitor i tekstopisac
umrli pre više od 70 godina (Srbija i EU), ili je narodna/tradicionalna bez
poznatog autora. Za SAD važi i da je sve objavljeno pre 1931. slobodno.

Šta je u fajlovima: samo melodija (nota po nota) i oznake akorda. Tekstova
pesama nema (`"language": "instrumental"`), a aranžmane je napravila sama
aplikacija skriptom `tools/make_songs.py` iz osnovne melodije, pa nijedan tuđi
moderni aranžman ili tab nije preuzet. Srpski nazivi su naši prevodi.

## Glavni katalog (učitava se podrazumevano): sve u redu

| Pesma | Autor | Zašto je slobodna |
|---|---|---|
| Twinkle Twinkle, Mary Had a Little Lamb, Frère Jacques, Row Your Boat, Old MacDonald, Hot Cross Buns, London Bridge, Yankee Doodle, Pop Goes the Weasel, My Bonnie, Drunken Sailor, When the Saints, Greensleeves, We Wish You a Merry Christmas | narodne | tradicionalne, 16.-19. vek |
| Clementine | Percy Montrose (1884) | objavljeno pre 1931, autor umro davno |
| Ode to Joy, Für Elise | Beethoven (u. 1827) | |
| Silent Night | Gruber (u. 1863) | |
| Jingle Bells | Pierpont (u. 1893) | |
| Amazing Grace | Newton (u. 1807), melodija iz 1829. | |
| Auld Lang Syne | Burns (u. 1796), narodna melodija | |
| Minuet in G | Petzold (u. 1733) | |
| In the Hall of the Mountain King | Grieg (u. 1907) | |
| Happy Birthday | Mildred Hill (u. 1916), Patty Hill (u. 1946) | jedina "granična": u EU/Srbiji slobodna od 1. 1. 2017. (70 god. od 1946); u SAD sud je 2015. presudio da Warner nema prava, od 2016. slobodna |

## Nove pesme u ovom PR-u

| Pesma | Autor | Zašto je slobodna |
|---|---|---|
| Brahms' Lullaby | Brahms (u. 1897) | |
| Oh! Susanna | Stephen Foster (u. 1864) | |
| O Christmas Tree | nemačka narodna, tekst Anschütz 1824 | |
| Deck the Halls | velška narodna "Nos Galan" | |
| Korobeiniki | ruska narodna, pesma Nekrasova 1861 | samo narodna melodija; aranžman iz igre Tetris NIJE korišćen |
| Largo (Novi svet) | Dvořák (u. 1904) | instrumentalno; engleski tekst "Goin' Home" (Fisher, u. 1945) nije uključen |
| Good King Wenceslas | Piae Cantiones 1582, tekst Neale 1853 | |
| Lightly Row (Hänschen klein) | nemačka narodna, tekst 1860 | |
| Alle meine Entchen | nemačka narodna dečja | |

## Sporno: katalog `extra/` (nije slobodan)

`extra/` (Metallica: Enter Sandman, Nothing Else Matters; Black Sabbath: War
Pigs) i originalni `.gp3` fajlovi u `import/extra/` su pod autorskim pravima.
Aplikacija ih ne prikazuje sama od sebe, ali repo i GitHub Pages su javni, pa
svako može da ih preuzme. To je deljenje tuđeg dela bez dozvole.

## Pesme koje izgledaju narodno, a nisu slobodne (ne dodavati)

- Kookaburra (Marion Sinclair, 1932), This Land Is Your Land (Guthrie, u. 1967),
  We Shall Overcome, Kumbaya (sporno autorstvo).
- Cielito Lindo (Quirino Mendoza y Cortés, u. 1957): slobodna tek od 2028.
- Moderne verzije narodnih pesama: House of the Rising Sun (Animals),
  Scarborough Fair (Simon & Garfunkel). Narodna melodija je slobodna, ali
  njihov aranžman nije, pa se lako pogreši.
- Srpske "starogradske" i pesme kao Tamo daleko: često imaju poznatog autora
  ili sporno autorstvo, pa svaku treba proveriti pre dodavanja.
