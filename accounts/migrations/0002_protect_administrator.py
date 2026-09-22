from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunSQL(
        sql="""
        CREATE FUNCTION protect_classroom_administrator() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.is_admin THEN
                    RAISE EXCEPTION 'The sole administrator cannot be deleted';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.id <> OLD.id THEN
                RAISE EXCEPTION 'Account IDs are immutable';
            END IF;
            IF OLD.is_admin AND (NOT NEW.is_admin OR NOT NEW.is_active) THEN
                RAISE EXCEPTION 'The sole administrator cannot be demoted or disabled';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER protect_classroom_administrator
        BEFORE UPDATE OR DELETE ON accounts_user
        FOR EACH ROW EXECUTE FUNCTION protect_classroom_administrator();
        """,
        reverse_sql="""
        DROP TRIGGER protect_classroom_administrator ON accounts_user;
        DROP FUNCTION protect_classroom_administrator();
        """,
    )]
