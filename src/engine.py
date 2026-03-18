"""象棋引擎接口模块
使用Pikafish（中国象棋版Stockpip install pikafish
"""
import pikafish

def get_best_move(fen: str) -> str:
    """获取当前局面的最佳走法
    
    Args:
        fen: 中国象棋FEN局面字符串（示例：rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1）
    
    Returns:
        最佳走法字符串（格式如'h2e2'），失败返回空字符串
    """
    engine = pikafish.Engine()
    
    try:
        engine.set_fen_position(fen)
        
        best_move = engine.get_best_move(depth=15)
        

        return best_move if best_move else ""
    
    except Exception as e:
        print(f"引擎调用失败：{e}")
        return ""
    
    finally:
        engine.quit()

if __name__ == "__main__":
    initial_fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
    best_move = get_best_move(initial_fen)
    print(f"最佳走法：{best_move}")