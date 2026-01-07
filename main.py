# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


# Press the green button in the gutter to run the script.

# See PyCharm help at https://www.jetbrains.com/help/pycharm/

from repl.repl import run_repl
from scenarios.simple_scenario import build_game

if __name__ == "__main__":
    game = build_game()
    run_repl(game)