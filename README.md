# Elite Dangerous Carrier Manager (EDCM)
![GitHub Release](https://img.shields.io/github/v/release/skywalker-elite/Elite-Dangerous-Carrier-Manager) ![GitHub Release Date](https://img.shields.io/github/release-date/skywalker-elite/Elite-Dangerous-Carrier-Manager) ![GitHub License](https://img.shields.io/github/license/skywalker-elite/Elite-Dangerous-Carrier-Manager) ![GitHub Download Count](https://img.shields.io/github/downloads/skywalker-elite/Elite-Dangerous-Carrier-Manager/total) ![GitHub Repo stars](https://img.shields.io/github/stars/skywalker-elite/Elite-Dangerous-Carrier-Manager)
![Banner](images_readme/EDCM_Banner.png)
EDCM is a third-party tool that helps you keep track of all your carriers in Elite Dangerous. The tool also provides some auxiliary functions to help with your daily trading and financial management.


![Jumps tab](images_readme/ss_jump.png)
Carrier location and jump countdown

![Trade tab](images_readme/ss_trade.png)
Trade overview

![Finance tab](images_readme/ss_finance.png)
Financial information at a glance

![Services](images_readme/ss_services.png)
Sees all services available on your carriers

![Miscellaneous](images_readme/ss_miscellaneous.png)
Miscellaneous information about your carriers

![Trade post](images_readme/ss_trade_post.png)
Easy trade posting

## Supported Game Versions
EDCM is designed to work with the **Live** version of the game. 
## Supported Platforms
Currently Windows 11 and Linux are supported. Windows 7/8/10 *should* work fine but has not been tested. 
## Features
### Main Features
- Real-time location of all your fleet carriers
- Real-time jump countdowns and jump status (i.e. jump locked, pad locked, cooldown)
- Credit balance overview of all carriers and their respective CMDRs
- Calculates how long your carriers are funded for upkeep
- Trade overview of all carriers
- Services overview of all carriers
- Highlights carriers in decommision process in red
- Other information about your carriers (when it was bought, docking permissions, etc.)
### Trade Overview
- Shows all buy and sell orders for all carriers
- Shows the amount, commodity, price, and when you set it of each trade order
### Trading Assist
- Generate jump countdowns timers in hammertime format
- Generate trade post command/snippet
  - After a buy/sell order is set, you can click `Post Trade` to auto generate the command/snippet to post your trade
  - The tool will read the system, type of order, commodity, and number units, as well as retrieve the list of stations in the system
  - You only need to select which station you are trading with and put in the profit and click OK
  - The command will then be copied to your clipboard for you to post it
### Booze Cruise Assist
- Shows N# for systems on the ladder
  - For example, when your carrier is in the system `Gali`, it will be displayed as `N16 (Gali)`
- Post departure notice
  - After a jump is plotted to/from above N2, the wine carrier departure command can be generated and copied to your clipboard with click of a button
- Wine unload command
  - After wine sell order is set and the carrier is at the peak, a wine unload command will be generated and copied to your clipboard after clicking the `Post Trade` button
- Timer reminder
  - You can enter the swap timer provided to you and you will get a reminder to plot your jump 2 minutes prior and another at the exact time
  - Do Not rely on this feature to plot your jump! You are solely responsible to plot your jump on time, this is only a reminder in case you get distracted
### Jump Status Notification
- You can set up notifications for the following events:
  - Jump plotted
  - Jump completed
  - Jump cancelled
  - Cooldown finished
- Each notification can be in the form of a popup message, playing a sound, sending a message to a Discord channel (with or without a ping), or a combination of all three
- You can customize notifications for each event
- You can specify the audio file (.mp3 or .wav) to play for each event
## Installation
Simply download the EDCM.exe (or EDCM-linux for linux) file from releases and launch it. 
The first time you run EDCM, it will ask if you want to create a settings file. Click yes and it will create one using the default settings.
You can edit the settings file using any text editor to change the settings to your liking.
## Settings
The settings file is a toml file that contains all the settings for EDCM. You can edit it to change the settings to your liking. 
### How to edit the settings file
1. Go to the options tab, click the `Open Settings File` button
2. If prompted, choose your text editor of choice (notepad, notepad++, etc.)
3. Change the settings to your liking
4. Save the file and close the text editor
5. Click the `Reload Settings` button in EDCM to apply the changes
6. EDCM will check if the settings file is valid, if not, correct the errors and try again
### Suggested things to change
- **trade_post** section
  - Make sure the trade post format matches what you want to use (the default is PTN CCO format, with ACO format commented out for you to uncomment)
- **notification** section
  - Enable the notifications you want to use
  - Set the notification sound to your desired sound file if you want to use a custom sound (.mp3 or .wav). The default is a simple TTS announcement
- **discord** section
  - Set the Discord webhook URL to your webhook of an appropriate channel if you want to use the Discord notification feature
  - Set the userID to your discord user ID if you want to use the ping feature
- It's recommended to test your settings in the options tab for the first time you set them up
## Limitations
Some limitations may be addressed in later updates thoon, maybe, eventually... don't count on it
- EDCM is currently English only
- EDCM relies on your local journal files
  - If you have moved, deleted or otherwise modified your journal files it may result in inaccurate information or unexpected behavior
  - If you play on multiple machines, you will need to find a way to sync up your journal files
- Trade overview might contain "ghost" orders for both buy and sell
  - This is due to the way the game journal logs trade orders, EDCM is not aware of whether a buy order has been filled
  - For sell orders, this will help you eliminate the ghost sell orders in the carrier management menu in-game, which also contains ghost sell orders (shown as exporting)
  - To eliminate ghost sell orders, follow the steps below:
    1. Set a buy order for the commodity with ghost sell
    2. Cancel the buy order
  - You can follow the similar steps for buy orders, but those only affects EDCM, not the in-game carrier management menu
  - TL;DR: Any trade orders you haven't manually cancelled in-game will show up
- The post trade function
  - It uses <a href=https://www.edsm.net>EDSM</a> to retrieve the list of stations in system. It may result in an error if it can't reach it
- Balance updates
  - Carrier balances are updated everytime you open up your carrier management menu
  - CMDR balances only updates on log-in, if you just bought the carrier, you will need to log out and back in to see the CMDR balance
## Known Issues
- Launching it takes a good while and may appear unresponsive or not show anything while it's loading, just give it some time, I promise it'll show up, *usually*. 
- It may consume a bit more CPU and ram than you expected but shouldn't be *too* bad
## Acknowledgements
Thank you <a href=https://github.com/aussig>aussig</a> for the <a href=https://github.com/aussig/BGS-Tally/tree/develop/data>lists of commodities</a>, related files are in the `3rdParty\aussig.BGS-Tally` folder with the corresponding license file. 
## Disclaimers
Although influenced a lot by the <a href=https://pilotstradenetwork.com>Pilots Trade Network (PTN)</a> in its design, EDCM is not endorsed by or affliated with the PTN and is not an offical tool of any player group. 

EDCM is a third-party tool and is not affiliated with or endorsed by Frontier Developments, the developers of Elite Dangerous. 