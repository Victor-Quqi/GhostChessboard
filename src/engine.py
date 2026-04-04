"""Minimal Xiangqi engine wrapper based on Pikafish."""
import pikafish

def get_best_move(fen: str) -> str:
    """Return the best move for a Xiangqi FEN position."""
    engine = pikafish.Engine()
    
    try:
        engine.set_fen_position(fen)
        
        best_move = engine.get_best_move(depth=15)
        return best_move if best_move else ""
    
    except Exception as e:
        print(f"Engine call failed: {e}")
        return ""
    
    finally:
        engine.quit()

if __name__ == "__main__":
    initial_fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
    best_move = get_best_move(initial_fen)
    print(f"Best move: {best_move}")
